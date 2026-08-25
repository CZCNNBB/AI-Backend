import os
import urllib.parse


class AgentCheckpointConfig:
    """Agent Checkpointer 配置对象。"""

    def __init__(
        self,
        *,
        checkpoint_type: str,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        schema: str,
    ):
        """
        初始化 Checkpointer 配置。

        Args:
            checkpoint_type: checkpointer 类型，当前支持 postgres、memory、none。
            host: PostgreSQL 主机。
            port: PostgreSQL 端口。
            database: PostgreSQL 数据库名。
            username: PostgreSQL 用户名。
            password: PostgreSQL 密码。
            schema: PostgreSQL schema，默认使用 agent。
        """
        self.checkpoint_type = checkpoint_type
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.schema = schema

    @classmethod
    def from_env(cls) -> "AgentCheckpointConfig":
        """
        从环境变量读取 Checkpointer 配置。

        Returns:
            AgentCheckpointConfig 配置对象。
        """
        return cls(
            checkpoint_type=os.getenv("CHECKPOINTER_TYPE", "postgres").strip().lower(),
            host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DATABASE", "career_ai"),
            username=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            schema=os.getenv("CHECKPOINTER_POSTGRES_SCHEMA", "agent"),
        )

    def get_standard_pg_url(self) -> str:
        """
        生成 LangGraph PostgreSQL checkpointer 使用的标准 PostgreSQL 连接串。

        Returns:
            标准 postgresql:// 连接串。注意这里不能使用 SQLAlchemy 的 postgresql+psycopg://。
        """
        encoded_user = urllib.parse.quote_plus(self.username)
        encoded_pwd = urllib.parse.quote_plus(self.password)
        encoded_options = urllib.parse.quote_plus(f"-csearch_path={self.schema},public")
        return (
            f"postgresql://{encoded_user}:{encoded_pwd}"
            f"@{self.host}:{self.port}/{self.database}"
            f"?options={encoded_options}"
        )
