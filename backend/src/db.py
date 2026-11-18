import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
_url=os.environ['DATABASE_URL']
_opts={'pool_pre_ping':True}
if not _url.startswith('sqlite'):_opts['isolation_level']="READ COMMITTED"  # MySQL 工单行锁后聚合读已提交数据
engine = create_engine(_url,**_opts)
Session = sessionmaker(engine, expire_on_commit=False)
class Base(DeclarativeBase): pass
def db_session():
    with Session() as s:
        yield s
