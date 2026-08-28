# 使用与本地开发环境一致的 Python 3.12，并固定 Debian 基础版本保证构建可复现。
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/ai-backend

# ca-certificates 用于访问 HTTPS 模型服务；libgomp1 供部分数值计算依赖在运行时使用。
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖清单，业务代码变化时可以复用依赖安装缓存层。
COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install --requirement requirements.txt

COPY app ./app

# 使用非 root 用户运行应用；上传文件写入独立持久化卷。
RUN groupadd --system ai-backend \
    && useradd --system --gid ai-backend --home-dir /opt/ai-backend ai-backend \
    && mkdir -p /data/uploads \
    && chown -R ai-backend:ai-backend /opt/ai-backend /data/uploads

USER ai-backend

EXPOSE 8090

# 使用 Python 标准库执行健康检查，避免仅为探活额外安装 curl。
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/', timeout=3)" || exit 1

# Linux 容器直接使用 asyncio 事件循环；生产环境关闭 reload，当前先保持单 Worker。
CMD ["python", "-B", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090", "--workers", "1"]
