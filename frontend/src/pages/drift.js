import {esc,localStamp,fixed} from '../utils/format.js';
import {notify,jobLabel} from '../components/press.js';
import {send} from '../api.js';

const stateClass=st=>({monitoring:'pass',warning:'fail',closed:''}[st]||'');
const driftTag=d=>{
  if(!d)return '<span class="status">待判读</span>';
  if(d==='stable')return '<span class="status pass">稳定</span>';
  if(d==='drift')return '<span class="status fail">漂移波动</span>';
  return '<span class="status">未纳入累计</span>';
};
function baselineBlock(c){
  const b=c.baseline||{};
  if(!c.baseline_ready||!b.ready){
    return `<p class="note">基线不足：${esc(b.reason||'参考训练合格张不足')}。封箱发货已暂停，补齐参考后由新周期生效。</p>`;
  }
  return `<div class="metricstrip">
    <div>训练合格基线张<b>${b.train_ok_count}</b></div>
    <div>留出合格张<b>${b.holdout_ok_count}</b></div>
    <div>留出误报率<b>${(b.holdout_false_alarm_rate*100).toFixed(1)}%</b></div>
    <div>单张|z|阈值<b>${fixed(b.z_limit,1)}</b></div>
  </div>
  <p class="muted">${esc(b.basis)}；留出误报样：${esc((b.holdout_false_alarm_codes||[]).join('/')||'无')}。${esc(b.holdout_note||'')}<br>
  基线编号（前8）：${esc((b.train_ok_codes||[]).slice(0,8).join('/'))}</p>
  <table class="matrix"><thead><tr><th>特征</th><th>基线均值</th><th>基线标准差</th></tr></thead><tbody>
  ${(b.feature_names||[]).map((n,i)=>`<tr><th>${esc(n)}</th><td>${fixed(b.mean[i],4)}</td><td>${fixed(b.std[i],4)}</td></tr>`).join('')}
  </tbody></table>`;
}
function sampleRows(s,c){
  return s.samples.filter(x=>x.cycle_id===c.id).sort((a,b)=>a.sequence-b.sequence).map(x=>{
    const p=s.proofs.find(q=>q.id===x.proof_id);
    const ev=x.drift_evidence||{};
    return `<article class="section sample" data-id="${x.id}">
      <div class="eyebrow">序${x.sequence} / ${esc(p?.code||'')} / ${localStamp(p?.classified_at)}</div>
      <h3>${driftTag(x.drift_state)} <span class="status ${x.state==='passed'?'pass':x.state==='held'?'fail':''}">${esc(x.state)}</span></h3>
      <p class="muted">四色${fixed(p?.density_c)}/${fixed(p?.density_m)}/${fixed(p?.density_y)}/${fixed(p?.density_k)} · 网点扩大${fixed(p?.dot_gain)}%
      ${ev.max_abs_z!=null?` · 最大|z|=${fixed(ev.max_abs_z,2)}`:''}${ev.over_features?.length?` · 越限：${esc(ev.over_features.map(o=>o.feature).join('、'))}`:''}${ev.note?` · ${esc(ev.note)}`:''}</p>
    </article>`;
  }).join('')||'<p class="note">本周期尚无量产抽检。</p>';
}
export function render(s){
  return `<div class="head"><div>
    <div class="eyebrow">DRIFT / CYCLE / RELEASE / 10</div>
    <h1>连续合格也会漂移，证据够了才冻结放行。</h1>
    <p>每张开机单独立漂移监测周期：基线只用参考训练合格张，留出张只评估误报，量产张不参与拟合。按取样序号累计，单张波动不触发，连续3张同向漂移才预警并冻结封箱发货；主管调机后以新取连续3张稳定样确认解除，再起新周期。</p>
  </div></div>
  <section class="section"><h2>各开机单漂移状态</h2>${s.driftCycles.length?s.driftCycles.map(c=>{
    const job=s.jobs.find(j=>j.id===c.job_id);
    return `<article class="section hold" data-cycle="${c.id}">
      <div class="eyebrow">${jobLabel(s,c.job_id)} / 第${c.cycle_no}周期 / 建周期 ${localStamp(c.created_at)}</div>
      <h2><span class="status ${stateClass(c.state)}">${esc({monitoring:'监测中',warning:'漂移预警·冻结封箱发货',closed:'已解除闭合'}[c.state]||c.state)}</span>
      ${!c.baseline_ready?'<span class="status fail">基线不足·暂停放行</span>':''}</h2>
      ${c.state==='warning'?`<p class="note">${esc(c.reason)}<br>触发样张：${esc((c.trigger_codes||[]).join(' / '))}</p>`:''}
      ${c.state==='closed'?`<p class="note">解除人 ${esc(c.cleared_by)} · ${localStamp(c.cleared_at)}<br>调机依据：${esc(c.resolution)}<br>确认稳定样：${esc((c.confirm_sample_ids||[]).map(id=>s.proofs.find(p=>p.id===s.samples.find(x=>x.id===id)?.proof_id)?.code).filter(Boolean).join(' / '))}</p>`:''}
      <p class="muted">连续漂移计数 ${c.drift_streak} / 3 · 预警后连续稳定 ${c.stable_streak} / 3 · 已评估 ${c.evaluated_count} 张</p>
      <h3>基线依据</h3>${baselineBlock(c)}
      ${c.state==='warning'?`<form class="drift-clear" data-key="${c.id}">
        <label>主管调机与解除依据（至少5字）</label>
        <textarea name="resolution" minlength="5" required placeholder="已调整供水/供墨，连续3张新取样密度回归基线区间"></textarea>
        <div class="actions"><button class="magenta" ${s.user.role==='admin'?'':'disabled'}>确认连续稳定样并解除预警，再起监测周期</button></div>
        ${c.stable_streak<3?`<p class="note">还需 ${3-c.stable_streak} 张调机后新取稳定样，当前不能解除。</p>`:''}
      </form>`:''}
      <h3>本周期样张证据</h3>${sampleRows(s,c)}
    </article>`;
  }).join(''):'<p class="note">暂无监测周期；量产工单首次抽检时自动按当前参考基线开启。</p>'}</section>`;
}
export function bind(s,reload){
  document.querySelectorAll('.drift-clear').forEach(f=>f.onsubmit=async e=>{
    e.preventDefault();
    try{await send('/drift-cycles/'+f.dataset.key+'/clear',Object.fromEntries(new FormData(f)));await reload();notify('漂移预警已解除，新监测周期已开启');}
    catch(err){notify(err.message);}
  });
}
