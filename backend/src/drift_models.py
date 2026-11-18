from sqlalchemy import String,Integer,ForeignKey,JSON,UniqueConstraint,CheckConstraint
from sqlalchemy.orm import Mapped,mapped_column
from .db import Base
class DriftCycle(Base):
    __tablename__='drift_cycles'
    # 每个开机单的一个漂移监测周期；解除预警后旧周期closed并另起新周期
    id:Mapped[int]=mapped_column(primary_key=True)
    job_id:Mapped[int]=mapped_column(ForeignKey('print_jobs.id'))
    cycle_no:Mapped[int]=mapped_column()
    state:Mapped[str]=mapped_column(String(24),default='monitoring')  # monitoring/warning/closed
    baseline_ready:Mapped[bool]=mapped_column(default=False)
    baseline:Mapped[dict|None]=mapped_column(JSON,nullable=True)      # 参考训练合格张均值/标准差/编号/留出误报
    drift_streak:Mapped[int]=mapped_column(Integer,default=0)        # 按取样序号累计的连续漂移波动张数
    stable_streak:Mapped[int]=mapped_column(Integer,default=0)       # 预警后新取连续稳定样计数
    evaluated_count:Mapped[int]=mapped_column(Integer,default=0)
    triggered_sample_id:Mapped[int|None]=mapped_column(ForeignKey('press_samples.id'),nullable=True)
    trigger_codes:Mapped[list]=mapped_column(JSON,default=list)      # 触发预警保留的连续漂移样张
    reason:Mapped[str]=mapped_column(String(500),default='')
    created_at:Mapped[str]=mapped_column(String(40))
    cleared_by:Mapped[str]=mapped_column(String(100),default='')
    cleared_at:Mapped[str|None]=mapped_column(String(40),nullable=True)
    resolution:Mapped[str]=mapped_column(String(500),default='')
    confirm_sample_ids:Mapped[list]=mapped_column(JSON,default=list) # 解除所凭的连续稳定样
    __table_args__=(UniqueConstraint('job_id','cycle_no'),CheckConstraint('cycle_no>0 AND drift_streak>=0 AND stable_streak>=0'))
