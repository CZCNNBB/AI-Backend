import asyncio
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from app.common.db.postgres_db import postgres_transaction
from app.server.file.src.config.file_config import FileServiceConfig
from app.server.file.src.logging_config import logger
from app.server.file.src.repository.file_repository import FileRepository
from app.server.file.src.service.file_service import FileService


class TemporaryFileCleanupManager:
    """按配置周期清理超过保留期限的 Agent 临时附件。"""

    def __init__(
        self,
        repository: FileRepository | None = None,
        file_service: FileService | None = None,
        config: FileServiceConfig | None = None,
    ) -> None:
        """初始化临时文件清理器及其生命周期状态。

        Args:
            repository: 文件记录数据访问层。
            file_service: 文件服务，用于解析当前上传根目录。
            config: 文件服务和清理任务配置。
        """
        self.config = config or FileServiceConfig.from_env()
        self.repository = repository or FileRepository()
        self.file_service = file_service or FileService(config=self.config)
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    async def startup(self) -> None:
        """在应用启动时创建后台清理任务。"""
        if not self.config.cleanup_enabled:
            logger.info("临时文件定时清理已关闭。")
            return
        if self._task is not None and not self._task.done():
            return

        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run_loop(),
            name="temporary-file-cleanup",
        )
        logger.info(
            "临时文件定时清理已启动: retention_hours=%s interval_seconds=%s batch_size=%s",
            self.config.temporary_retention_hours,
            self.config.cleanup_interval_seconds,
            self.config.cleanup_batch_size,
        )

    async def close(self) -> None:
        """在应用退出时停止后台清理任务并等待其结束。"""
        if self._task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()

        await self._task
        self._task = None
        self._stop_event = None
        logger.info("临时文件定时清理已停止。")

    async def _run_loop(self) -> None:
        """循环执行清理，并在两次扫描之间等待配置的时间。"""
        while self._stop_event is not None and not self._stop_event.is_set():
            try:
                # 数据库与本地文件操作均为同步阻塞调用，放入线程池避免阻塞事件循环。
                deleted_count = await asyncio.to_thread(self.cleanup_once)
                if deleted_count > 0:
                    logger.info("本轮临时文件清理完成: deleted_count=%s", deleted_count)
            except Exception:
                # 单轮失败不能终止后台任务，下一个周期仍然继续尝试清理。
                logger.exception("临时文件定时清理执行失败。")

            if self._stop_event is None or self._stop_event.is_set():
                break
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.config.cleanup_interval_seconds,
                )
            except TimeoutError:
                # 等待超时表示已经到达下一次正常扫描时间。
                continue

    def cleanup_once(self) -> int:
        """在一个短事务中领取并清理一批过期临时文件。

        Returns:
            本轮成功删除的文件记录数量。
        """
        created_before = datetime.now() - timedelta(hours=self.config.temporary_retention_hours)
        deleted_file_ids: list[str] = []

        with postgres_transaction() as db:
            records = self.repository.list_expired_temporary_files(
                db=db,
                created_before=created_before,
                limit=self.config.cleanup_batch_size,
            )
            for record in records:
                if not self._delete_file_directory(record.storage_path, record.file_id):
                    continue
                deleted_file_ids.append(record.file_id)

            self.repository.delete_by_ids(db, deleted_file_ids)

        return len(deleted_file_ids)

    def _delete_file_directory(self, storage_path: str, file_id: str) -> bool:
        """校验文件目录位于上传根目录内，然后删除整个 file_id 目录。

        Args:
            storage_path: 数据库记录的原始文件完整路径。
            file_id: 文件唯一标识，用于日志定位。

        Returns:
            路径安全且目录已删除或本就不存在时返回 True。
        """
        upload_root = self.file_service.get_upload_dir().resolve()
        file_directory = Path(storage_path).resolve().parent
        try:
            relative_directory = file_directory.relative_to(upload_root)
        except ValueError:
            logger.error(
                "跳过不在上传根目录内的临时文件: file_id=%s storage_path=%s upload_root=%s",
                file_id,
                storage_path,
                upload_root,
            )
            return False

        # 标准上传目录必须恰好是根目录下的一层 file_id，避免误删根目录或相邻目录。
        if len(relative_directory.parts) != 1 or relative_directory.name != file_id:
            logger.error(
                "跳过目录结构异常的临时文件: file_id=%s file_directory=%s",
                file_id,
                file_directory,
            )
            return False

        if file_directory.exists():
            shutil.rmtree(file_directory)
        return True


temporary_file_cleanup_manager = TemporaryFileCleanupManager()
