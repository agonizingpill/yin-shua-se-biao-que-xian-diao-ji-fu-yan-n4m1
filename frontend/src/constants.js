export const ROLES={admin:'印刷主管',pressman:'机长',viewer:'只读观察员'};
export const DEFECTS=['合格','乳化','偏色'];
export const STATES={hold:'量产停机',setup:'待开机',adjusting:'调机复验中',production:'已签印量产',issued:'指令待执行',executed:'已执行待复验',signed:'复验闭合',unmeasured:'未判读',classifying:'判读中',classified:'已判读',failed:'判读失败',monitoring:'漂移监测中',warning:'漂移预警·冻结封箱',closed:'预警已解除·周期闭合',stable:'稳定',drift:'漂移波动',skipped:'未纳入累计'};
export const DRIFT_STATES={stable:['稳定','pass'],drift:['漂移波动','fail'],skipped:['未纳入','']};
