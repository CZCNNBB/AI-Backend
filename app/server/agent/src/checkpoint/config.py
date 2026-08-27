import os
import re
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
        connect_timeout: int,
        pool_min_size: int,
        pool_max_size: int,
        pool_timeout: float,
        pool_startup_timeout: float,
        pool_max_idle: float,
        pool_max_lifetime: float,
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
            connect_timeout: 建立单条 PostgreSQL 连接的超时时间。
            pool_min_size: Checkpointer 连接池最小连接数。
            pool_max_size: Checkpointer 连接池最大连接数。
            pool_timeout: 从连接池等待可用连接的超时时间。
            pool_startup_timeout: 应用启动时等待连接池就绪的超时时间。
            pool_max_idle: 池内空闲连接的最长保留时间。
            pool_max_lifetime: 单条连接的最长生命周期。
        """
        self.checkpoint_type = checkpoint_type
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.schema = schema
        self.connect_timeout = connect_timeout
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size
        self.pool_timeout = pool_timeout
        self.pool_startup_timeout = pool_startup_timeout
        self.pool_max_idle = pool_max_idle
        self.pool_max_lifetime = pool_max_lifetime
        self.validate()

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
            connect_timeout=cls._read_int_env("POSTGRES_CONNECT_TIMEOUT", 5),
            pool_min_size=cls._read_int_env("CHECKPOINTER_POOL_MIN_SIZE", 1),
            pool_max_size=cls._read_int_env("CHECKPOINTER_POOL_MAX_SIZE", 5),
            pool_timeout=cls._read_float_env("CHECKPOINTER_POOL_TIMEOUT", 10),
            pool_startup_timeout=cls._read_float_env(
                "CHECKPOINTER_POOL_STARTUP_TIMEOUT",
                15,
            ),
            pool_max_idle=cls._read_float_env("CHECKPOINTER_POOL_MAX_IDLE", 300),
            pool_max_lifetime=cls._read_float_env(
                "CHECKPOINTER_POOL_MAX_LIFETIME",
                1800,
            ),
        )

    @staticmethod
    def _read_int_env(name: str, default: int) -> int:
        """读取整数环境变量，格式错误时抛出包含变量名的异常。"""
        raw_value = os.getenv(name)
        if raw_value is None or not raw_value.strip():
            return default
        try:
            return int(raw_value)
        except ValueError as error:
            raise ValueError(f"环境变量 {name} 必须是整数") from error

    @staticmethod
    def _read_float_env(name: str, default: float) -> float:
        """读取浮点环境变量，格式错误时抛出包含变量名的异常。"""
        raw_value = os.getenv(name)
        if raw_value is None or not raw_value.strip():
            return default
        try:
            return float(raw_value)
        except ValueError as error:
            raise ValueError(f"环境变量 {name} 必须是数字") from error

    def validate(self) -> None:
        """校验 Checkpointer 类型、Schema 和连接池参数。"""
        supported_types = {"postgres", "memory", "none"}
        if self.checkpoint_type not in supported_types:
            raise ValueError(
                "CHECKPOINTER_TYPE 只支持 postgres、memory、none，"
                f"当前值为: {self.checkpoint_type}"
            )

        # Schema 会进入 PostgreSQL search_path，必须限制为普通标识符，避免配置注入。
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.schema):
            raise ValueError(
                "CHECKPOINTER_POSTGRES_SCHEMA 必须是合法 PostgreSQL 标识符"
            )
        if self.port <= 0 or self.port > 65535:
            raise ValueError("POSTGRES_PORT 必须在 1 到 65535 之间")
        if self.connect_timeout <= 0:
            raise ValueError("POSTGRES_CONNECT_TIMEOUT 必须大于 0")
        if self.pool_min_size < 0:
            raise ValueError("CHECKPOINTER_POOL_MIN_SIZE 不能小于 0")
        if self.pool_max_size < 1:
            raise ValueError("CHECKPOINTER_POOL_MAX_SIZE 必须大于等于 1")
        if self.pool_min_size > self.pool_max_size:
            raise ValueError(
                "CHECKPOINTER_POOL_MIN_SIZE 不能大于 CHECKPOINTER_POOL_MAX_SIZE"
            )

        positive_float_values = {
            "CHECKPOINTER_POOL_TIMEOUT": self.pool_timeout,
            "CHECKPOINTER_POOL_STARTUP_TIMEOUT": self.pool_startup_timeout,
            "CHECKPOINTER_POOL_MAX_IDLE": self.pool_max_idle,
            "CHECKPOINTER_POOL_MAX_LIFETIME": self.pool_max_lifetime,
        }
        for variable_name, value in positive_float_values.items():
            if value <= 0:
                raise ValueError(f"{variable_name} 必须大于 0")

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
