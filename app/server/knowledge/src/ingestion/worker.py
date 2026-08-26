"""知识入库后台 Worker。"""

import asyncio
import socket
from contextlib import suppress
from uuid import uuid4

from app.server.knowledge.src.config import knowledge_config
from app.server.knowledge.src.ingestion.executor import ingestion_executor
from app.server.knowledge.src.ingestion.queue_service import ingestion_queue_service
from app.server.knowledge.src.logging_config import logger
from app.server.knowledge.src.models import IngestionRun


class IngestionWorkerManager:
    """管理当前进程内的知识入库 Worker 和任务心跳。"""

    def __init__(self) -> None:
        """初始化停止事件和 Worker 任务集合。"""
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._worker_prefix = f"{socket.gethostname()}-{uuid4().hex[:8]}"

    async def start(self) -> None:
        """启动知识入库 Worker；重复调用时保持幂等。"""
        if self._tasks:
            return

        # Worker 一旦启用就要求数据库结构完整，避免后台任务静默崩溃。
        await asyncio.to_thread(ingestion_queue_service.check_schema)
        self._stop_event.clear()
        for index in range(knowledge_config.ingestion_worker_count):
            worker_id = f"{self._worker_prefix}-{index + 1}"
            self._tasks.append(
                asyncio.create_task(
                    self._worker_loop(worker_id, recover_stale=index == 0),
                    name=f"knowledge-ingestion-{index + 1}",
                )
            )
        logger.info(
            "知识入库 Worker 已启动: count=%s prefix=%s",
            len(self._tasks),
            self._worker_prefix,
        )

    async def stop(self) -> None:
        """停止抢占新任务并取消当前进程内 Worker。"""
        if not self._tasks:
            return
        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        logger.info("知识入库 Worker 已停止")

    async def _worker_loop(self, worker_id: str, *, recover_stale: bool) -> None:
        """循环抢占并执行任务，其中一个 Worker 定期负责僵尸任务恢复。"""
        last_recovery_at = 0.0
        loop = asyncio.get_running_loop()
        while not self._stop_event.is_set():
            try:
                if recover_stale and loop.time() - last_recovery_at >= knowledge_config.ingestion_recovery_interval_seconds:
                    await asyncio.to_thread(
                        ingestion_queue_service.recover_stale,
                        knowledge_config.ingestion_stale_seconds,
                        knowledge_config.ingestion_retry_delay_seconds,
                    )
                    last_recovery_at = loop.time()

                run = await asyncio.to_thread(ingestion_queue_service.claim_next, worker_id)
                if run is None:
                    await self._wait_for_next_poll()
                    continue
                await self._execute_claimed_run(worker_id, run)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                # 数据库短暂不可用时保留 Worker 循环，等待下一轮继续尝试。
                logger.exception("知识入库 Worker 轮询失败: worker_id=%s", worker_id)
                await self._wait_for_next_poll()

    async def _execute_claimed_run(self, worker_id: str, run: IngestionRun) -> None:
        """执行已抢占任务，并在执行期间独立维持数据库心跳。"""
        started_at = asyncio.get_running_loop().time()
        logger.info(
            "知识入库任务开始: run_id=%s worker_id=%s knowledge_id=%s file_id=%s operation=%s",
            run.run_id,
            worker_id,
            run.knowledge_id,
            run.file_id,
            run.operation,
        )
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(run.run_id, worker_id))
        try:
            await ingestion_executor.execute(run)
            await asyncio.to_thread(ingestion_queue_service.mark_completed, run.run_id, worker_id)
            logger.info(
                "知识入库任务完成: run_id=%s worker_id=%s elapsed_seconds=%.3f",
                run.run_id,
                worker_id,
                asyncio.get_running_loop().time() - started_at,
            )
        except asyncio.CancelledError:
            # 进程关闭时保留 running 状态，其他实例或下次启动会通过心跳超时恢复任务。
            logger.warning(
                "知识入库任务因 Worker 停止而中断: run_id=%s worker_id=%s elapsed_seconds=%.3f",
                run.run_id,
                worker_id,
                asyncio.get_running_loop().time() - started_at,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            final_status = await asyncio.to_thread(
                ingestion_queue_service.mark_failed_or_retry,
                run.run_id,
                worker_id,
                str(exc),
                knowledge_config.ingestion_retry_delay_seconds,
            )
            logger.exception(
                "知识入库任务失败: run_id=%s worker_id=%s next_status=%s elapsed_seconds=%.3f",
                run.run_id,
                worker_id,
                final_status,
                asyncio.get_running_loop().time() - started_at,
            )
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _heartbeat_loop(self, run_id: str, worker_id: str) -> None:
        """按固定间隔刷新任务心跳，任务失去所有权后自动结束。"""
        while True:
            await asyncio.sleep(knowledge_config.ingestion_heartbeat_seconds)
            owned = await asyncio.to_thread(ingestion_queue_service.heartbeat, run_id, worker_id)
            if not owned:
                return

    async def _wait_for_next_poll(self) -> None:
        """空队列时等待轮询间隔，并允许 stop 事件提前唤醒。"""
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=knowledge_config.ingestion_poll_interval_seconds,
            )
        except TimeoutError:
            pass


ingestion_worker_manager = IngestionWorkerManager()
