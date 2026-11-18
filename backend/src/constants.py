ROLES=('admin','pressman','viewer')
DEFECTS=('合格','乳化','偏色')
JOB_STATES=('setup','adjusting','production','hold')
ADJUSTMENT_STATES=('issued','executed','signed')
# 漂移监测：基线只取参考训练张中的合格张，留出张仅评估误报，量产张不参与拟合
DRIFT_FEATURES=('青密度比','品红密度比','黄密度比','黑密度比','网点扩大率')
DRIFT_Z_LIMIT=3.0            # 单张任一标准化特征|z|超过该值记为漂移波动
DRIFT_TRIGGER_COUNT=3        # 连续漂移波动张数达到该值才预警（单张波动不触发）
DRIFT_STABLE_CONFIRM=3       # 预警后新取连续稳定样达到该值，主管方可解除
DRIFT_MIN_BASELINE=20        # 合格训练张低于该数，基线不足，暂停封箱发货
DRIFT_FAR_LIMIT=0.05         # 留出合格张误报率上限，仅提示不单独阻断
