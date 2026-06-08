"""数据库引擎与 session 管理。

设计原则：DB 不可用时路由引擎仍可工作。DB 仅用于审计记录持久化。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from airouter.models.db_models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_db(db_url: str = "sqlite:///./airouter.db") -> Engine:
    """初始化数据库引擎并创建所有表。

    Args:
        db_url: SQLAlchemy 连接字符串。默认 SQLite 文件，测试用 sqlite:///:memory:

    Returns:
        Engine 实例。
    """
    global _engine, _SessionLocal

    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    _engine = create_engine(db_url, connect_args=connect_args, echo=False)

    # SQLite 外键强制（默认 OFF）
    if db_url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)

    Base.metadata.create_all(bind=_engine)
    return _engine


def get_engine() -> Engine:
    """获取当前引擎（需先调用 init_db）。"""
    if _engine is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """获取数据库 session（上下文管理器，自动 commit/rollback）。

    Usage:
        with get_session() as session:
            session.add(record)
    """
    if _SessionLocal is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")

    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_dep() -> Generator[Session, None, None]:
    """FastAPI 依赖注入用（yield generator，不自动 commit）。

    Usage:
        @app.get("/")
        def endpoint(db: Session = Depends(get_session_dep)):
            ...
    """
    if _SessionLocal is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")

    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
