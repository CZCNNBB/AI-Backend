import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.common.db.postgres_db import get_db_session


def check_database() -> None:
    """
    检查 PostgreSQL 是否可连接，并确认能力层需要的 Agent 表是否存在。

    能力层不再检查岗位业务表；岗位表属于 orchestration-backend 的业务入库职责。
    """
    expected_tables = [
        ("agent", "agent_conversations"),
        ("agent", "agent_messages"),
        ("agent", "agent_templates"),
    ]
    try:
        with get_db_session() as db:
            # select 1 是最小连通性检查，可以快速确认账号、密码、端口、库名是否正确。
            health_result = db.exec(text("select 1")).one()

            # 从 information_schema 查询表，避免依赖 SQLModel 自动建表。
            table_sql = text(
                """
                select table_schema, table_name
                from information_schema.tables
                where table_schema = any(:schemas)
                  and table_name = any(:table_names)
                order by table_schema, table_name
                """
            )
            existing_tables = db.exec(
                table_sql,
                params={
                    "schemas": [item[0] for item in expected_tables],
                    "table_names": [item[1] for item in expected_tables],
                },
            ).all()
    except UnicodeDecodeError:
        print("database_health=failed")
        print("error=PostgreSQL 返回的连接错误信息无法按 UTF-8 解码。")
        print("hint=端口已通，但账号、密码、数据库权限或 pg_hba.conf 认证配置可能不正确。")
        return
    except SQLAlchemyError as error:
        print("database_health=failed")
        print(f"error={error}")
        return

    print(f"database_health={health_result}")
    print(f"existing_tables={list(existing_tables)}")
    print(f"expected_table_count={len(expected_tables)}")
    print(f"existing_table_count={len(existing_tables)}")


if __name__ == "__main__":
    check_database()
