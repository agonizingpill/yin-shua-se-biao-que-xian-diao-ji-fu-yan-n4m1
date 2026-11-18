import numpy as np
from sqlalchemy import select
from fastapi import HTTPException
from .models import PrintJob,ProofSheet
from .production_models import PressSample
from .drift_models import DriftCycle
from .classifier import reference_split,vector
from .constants import DRIFT_FEATURES,DRIFT_Z_LIMIT,DRIFT_TRIGGER_COUNT,DRIFT_STABLE_CONFIRM,DRIFT_MIN_BASELINE,DRIFT_FAR_LIMIT
from .services import audit,now
EPS=1e-6
def build_baseline(s):
    # 基线只用参考训练张中的合格张；留出张只用于评估误报；量产张从不参与拟合
    refs,train,test=reference_split(s)
    ok_train=[refs[i]for i in train if refs[i].label=='合格']
    ok_holdout=[refs[i]for i in test if refs[i].label=='合格']
    if len(ok_train)<DRIFT_MIN_BASELINE:
        return {'ready':False,'reason':f'参考训练合格张{len(ok_train)}张，低于{DRIFT_MIN_BASELINE}张，基线不足','train_ok_codes':[r.code for r in ok_train]}
    mat=np.array([vector(r)for r in ok_train])
    mean=mat.mean(axis=0);std=np.maximum(mat.std(axis=0),EPS)
    # 留出合格张误报率：用同一基线与同一|z|阈值，不参与拟合
    false_alarms=[]
    for r in ok_holdout:
        ev=evaluate(vector(r),mean,std)
        if ev['is_drift']:false_alarms.append(r.code)
    far=round(len(false_alarms)/len(ok_holdout),4)if ok_holdout else 0.0
    return {'ready':True,'feature_names':list(DRIFT_FEATURES),'mean':[round(float(v),5)for v in mean],'std':[round(float(v),5)for v in std],
            'z_limit':DRIFT_Z_LIMIT,'trigger_count':DRIFT_TRIGGER_COUNT,'stable_confirm':DRIFT_STABLE_CONFIRM,
            'train_ok_count':len(ok_train),'train_ok_codes':[r.code for r in ok_train],
            'holdout_ok_count':len(ok_holdout),'holdout_false_alarm_codes':false_alarms,'holdout_false_alarm_rate':far,
            'holdout_far_limit':DRIFT_FAR_LIMIT,'holdout_note':('留出合格张误报率超提示线，请复核基线'if far>DRIFT_FAR_LIMIT else '留出合格张误报率在提示线内'),
            'split_seed':42,'basis':'仅参考训练合格张拟合；留出张仅评估误报；量产张不参与拟合'}
def evaluate(features,mean,std):
    zs=[round(float((features[i]-mean[i])/max(float(std[i]),EPS)),4)for i in range(len(features))]
    over=[{'feature':DRIFT_FEATURES[i],'z':zs[i]}for i in range(len(zs))if abs(zs[i])>DRIFT_Z_LIMIT]
    return {'z_scores':dict(zip(DRIFT_FEATURES,zs)),'is_drift':bool(over),'over_features':over,
            'max_abs_z':round(max(abs(v)for v in zs),4),'z_limit':DRIFT_Z_LIMIT}
def ensure_cycle(s,job,u=None):
    # 取该工单最新周期；不存在则用当前参考基线开启新监测周期（中断恢复后沿用并继续累计）
    cycle=s.scalar(select(DriftCycle).where(DriftCycle.job_id==job.id).order_by(DriftCycle.cycle_no.desc()).with_for_update())
    if cycle and cycle.state!='closed':return cycle
    no=(cycle.cycle_no+1)if cycle else 1
    try:baseline=build_baseline(s)
    except ValueError as ex:baseline={'ready':False,'reason':str(ex),'train_ok_codes':[]}
    cycle=DriftCycle(job_id=job.id,cycle_no=no,state='monitoring',baseline_ready=bool(baseline.get('ready')),baseline=baseline,created_at=now())
    s.add(cycle);s.flush()
    if u:audit(s,u,f'开启漂移监测周期 工单{job.code} 第{no}周期 基线{"就绪"if cycle.baseline_ready else "不足"}')
    return cycle
def current_cycle(s,job_id):
    return s.scalar(select(DriftCycle).where(DriftCycle.job_id==job_id,DriftCycle.state!='closed').order_by(DriftCycle.cycle_no.desc()))
def bind_sample(s,job,item,u):
    cycle=ensure_cycle(s,job,u)
    item.cycle_id=cycle.id
    return cycle
def ingest(s,item,proof,u=None):
    # worker 判读返回后调用；仅按取样序号累计证据，幂等，重试不重复停机
    if item.drift_state:return
    cycle=s.get(DriftCycle,item.cycle_id)if item.cycle_id else None
    if not cycle or cycle.state=='closed':
        # 迟回的旧周期结果：只留痕，不影响新周期/新预警
        item.drift_state='skipped';item.drift_evidence={'note':'结果属于已关闭监测周期，仅留痕，不参与当前周期累计'};return
    base=cycle.baseline or {}
    if not cycle.baseline_ready or not base.get('ready'):
        item.drift_state='skipped';item.drift_evidence={'note':'基线不足，本张不纳入漂移累计','baseline_reason':base.get('reason','')};return
    mean=np.array(base['mean']);std=np.array(base['std'])
    job=s.get(PrintJob,item.job_id)
    ev=evaluate(vector(proof,job.target_density),mean,std)
    ev.update({'sample_sequence':item.sequence,'proof_code':proof.code,'cycle_no':cycle.cycle_no,
               'baseline_train_ok_count':base['train_ok_count'],
               'baseline_codes':base['train_ok_codes'][:8]+(['…']if len(base['train_ok_codes'])>8 else [])})
    cycle.evaluated_count+=1
    if proof.classification_state!='classified' or not proof.pass_flag or proof.defect!='合格':
        # 缺陷/判读失败走原停机处置，不充当漂移稳定依据，连续漂移计数在此中断
        item.drift_state='skipped';ev['note']='缺陷或判读失败走停机处置，不纳入漂移连续计数'
        item.drift_evidence=ev;cycle.drift_streak=0;return
    if ev['is_drift']:
        item.drift_state='drift';item.drift_evidence=ev
        cycle.drift_streak+=1;cycle.stable_streak=0
        if cycle.state=='monitoring' and cycle.drift_streak>=DRIFT_TRIGGER_COUNT:
            rows=s.scalars(select(PressSample).where(PressSample.cycle_id==cycle.id,PressSample.drift_state=='drift').order_by(PressSample.sequence.desc()).limit(DRIFT_TRIGGER_COUNT)).all()
            codes=[s.get(ProofSheet,r.proof_id).code for r in rows][::-1]
            cycle.state='warning';cycle.triggered_sample_id=item.id;cycle.trigger_codes=codes
            dirs='、'.join(f"{o['feature']}(z={o['z']})"for o in ev['over_features'])
            cycle.reason=f"连续{cycle.drift_streak}张合格样密度同向漂移仍被放行：{dirs}；触发样张{'/'.join(codes)}"
            if u:audit(s,u,f'漂移预警冻结封箱发货 工单{job.code} 第{cycle.cycle_no}周期 {cycle.reason}')
    else:
        item.drift_state='stable';item.drift_evidence=ev
        cycle.drift_streak=0
        if cycle.state=='warning':
            # 预警后以新取连续稳定样累计确认；期间任一漂移波动重新计数
            cycle.stable_streak+=1;cycle.confirm_sample_ids=[*(cycle.confirm_sample_ids or []),item.id]
        else:cycle.stable_streak=0
def gate(s,j):
    # 封箱/发货并发门禁：判读与封箱均先取工单行锁串行化，预警或基线不足一律拦截
    cycle=current_cycle(s,j.id)
    if not cycle:
        raise HTTPException(409,'漂移监测周期尚未建立，暂停封箱发货，请先完成一次量产抽检')
    if not cycle.baseline_ready:
        raise HTTPException(409,'漂移基线不足（参考训练合格张不够），暂停封箱发货')
    if cycle.state=='warning':
        raise HTTPException(409,f'漂移预警未解除，冻结封箱发货：{cycle.reason}')
    return cycle
def clear(s,key,p,u):
    cycle=s.scalar(select(DriftCycle).where(DriftCycle.id==key).with_for_update())
    if not cycle:raise HTTPException(404,'漂移监测周期不存在')
    job=s.scalar(select(PrintJob).where(PrintJob.id==cycle.job_id).with_for_update())
    # 缺陷停机仍须先走原复机流程
    from .production_models import PressHold
    if s.scalar(select(PressHold).where(PressHold.job_id==job.id,PressHold.state=='active')):raise HTTPException(409,'尚有活动缺陷停机单，须先主管复机后再解除漂移预警')
    resolution=p.resolution.strip()
    if cycle.state=='warning':
        # stable_streak 仅在预警后的稳定样上累加、遇任一漂移波动归零，恰为当前尾部连续稳定样长度
        if cycle.stable_streak<DRIFT_STABLE_CONFIRM:
            raise HTTPException(409,f'调机后须新取连续{DRIFT_STABLE_CONFIRM}张稳定样确认，当前连续{cycle.stable_streak}张，不能解除预警')
        confirm=s.scalars(select(PressSample).where(PressSample.cycle_id==cycle.id,PressSample.id.in_(cycle.confirm_sample_ids or [])).order_by(PressSample.sequence)).all()
        stable=[r for r in confirm if r.drift_state=='stable'][-DRIFT_STABLE_CONFIRM:]
        # 复核最后确认的若干张确为本周期最近的连续样，中间不得夹漂移/缺陷
        tail=s.scalars(select(PressSample).where(PressSample.cycle_id==cycle.id).order_by(PressSample.sequence.desc()).limit(DRIFT_STABLE_CONFIRM)).all()[::-1]
        if [r.id for r in tail]!=[r.id for r in stable] or any(r.drift_state!='stable' for r in tail):
            raise HTTPException(409,f'最近{DRIFT_STABLE_CONFIRM}张抽检并非连续稳定样，不能解除预警')
        codes=[s.get(ProofSheet,r.proof_id).code for r in stable]
        cycle.state='closed';cycle.cleared_by=u.email;cycle.cleared_at=now();cycle.resolution=resolution
        audit(s,u,f'主管解除漂移预警 工单{job.code} 第{cycle.cycle_no}周期 连续稳定样{"/".join(codes)} 依据{resolution}')
    elif cycle.state=='monitoring' and not cycle.baseline_ready:
        # 基线不足的暂停放行周期：补齐参考后由主管重建基线并重启，不要求稳定样
        try:fresh=build_baseline(s)
        except ValueError as ex:raise HTTPException(409,f'基线仍不足：{ex}')
        if not fresh.get('ready'):raise HTTPException(409,'基线仍不足，不能重启监测：'+fresh.get('reason',''))
        cycle.state='closed';cycle.cleared_by=u.email;cycle.cleared_at=now();cycle.resolution='重建基线重启：'+resolution
        audit(s,u,f'主管重建漂移基线并重启周期 工单{job.code} 第{cycle.cycle_no}周期 依据{resolution}')
    else:
        raise HTTPException(409,'仅预警中的监测周期或基线不足周期可以办理解除/重启')
    new=ensure_cycle(s,job,u)  # 再起监测周期，重新累计
    return cycle,new
