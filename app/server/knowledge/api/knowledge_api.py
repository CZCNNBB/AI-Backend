"""知识库服务统一接口。"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.common.db.postgres_db import get_postgres_engine
from app.common.schemas.result import Result
from app.server.knowledge.src.embedding.schemas import EmbeddingInput, EmbeddingOutput
from app.server.knowledge.src.ingestion.queue_service import ingestion_queue_service
from app.server.knowledge.src.retrieval.schemas import RetrievalInput, RetrievalOutput
from app.server.knowledge.src.schemas.knowledge_schemas import (
    IngestionCancelRequest,
    IngestionRetryRequest,
    IngestionRunListResponse,
    IngestionRunQueryRequest,
    IngestionRunResponse,
    IngestionRunSearchRequest,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseDeleteRequest,
    KnowledgeBaseQueryRequest,
    KnowledgeBaseResponse,
    KnowledgeBaseSearchRequest,
    KnowledgeBaseUpdateRequest,
    KnowledgeDocumentDeleteRequest,
    KnowledgeDocumentDeleteResponse,
    KnowledgeDocumentQueryRequest,
    KnowledgeDocumentReindexRequest,
    KnowledgeDocumentResponse,
    KnowledgeDocumentSearchRequest,
    KnowledgeDocumentSubmitRequest,
    KnowledgeDocumentSubmitResponse,
)
from app.server.knowledge.src.services.knowledge_management_service import (
    knowledge_management_service,
)
from app.server.knowledge.src.services.knowledge_service import knowledge_service
from app.server.knowledge.src.split.schemas import SplitInput, SplitOutput


router = APIRouter(prefix="/knowledge")


@router.get("/health", response_model=Result[dict[str, str]], summary="知识库服务存活检查")
def knowledge_health() -> Result[dict[str, str]]:
    """只检查知识库路由是否已经挂载，不检查外部依赖。"""
    return Result.success({"service": "knowledge", "status": "ok"})


@router.get("/health/readiness", response_model=Result[dict[str, Any]], summary="知识库依赖就绪检查")
async def knowledge_readiness() -> Result[dict[str, Any]]:
    """真实检查 PostgreSQL、Milvus 和模型服务是否可用。"""
    return Result.success(await knowledge_service.readiness())


@router.get("/capabilities", response_model=Result[dict[str, Any]], summary="查询知识库能力")
def get_knowledge_capabilities() -> Result[dict[str, Any]]:
    """查询当前已经接入的切片、向量化、检索和入库能力。"""
    return Result.success(knowledge_service.get_capabilities())


@router.post("/bases/create", response_model=Result[KnowledgeBaseResponse], summary="创建知识库")
async def create_knowledge_base(
    request: KnowledgeBaseCreateRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[KnowledgeBaseResponse]:
    """创建知识库记录和对应的 Milvus Collection。"""
    return Result.success(await knowledge_management_service.create_knowledge_base(db, request))


@router.post("/bases/detail", response_model=Result[KnowledgeBaseResponse], summary="查询知识库详情")
def get_knowledge_base(
    request: KnowledgeBaseQueryRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[KnowledgeBaseResponse]:
    """根据 knowledge_id 查询知识库详情。"""
    return Result.success(
        knowledge_management_service.get_knowledge_base(db, request.knowledge_id)
    )


@router.post("/bases/search", response_model=Result[list[KnowledgeBaseResponse]], summary="查询知识库列表")
def search_knowledge_bases(
    request: KnowledgeBaseSearchRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[list[KnowledgeBaseResponse]]:
    """按照关键字和状态查询知识库。"""
    return Result.success(knowledge_management_service.search_knowledge_bases(db, request))


@router.post("/bases/update", response_model=Result[KnowledgeBaseResponse], summary="修改知识库")
def update_knowledge_base(
    request: KnowledgeBaseUpdateRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[KnowledgeBaseResponse]:
    """修改知识库名称、描述、状态、元数据或默认切片配置。"""
    return Result.success(knowledge_management_service.update_knowledge_base(db, request))


@router.post("/bases/delete", response_model=Result[KnowledgeBaseResponse], summary="删除知识库")
async def delete_knowledge_base(
    request: KnowledgeBaseDeleteRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[KnowledgeBaseResponse]:
    """清理知识库向量与分块数据，并保留软删除记录用于审计。"""
    return Result.success(
        await knowledge_management_service.delete_knowledge_base(
            db, request.knowledge_id
        )
    )


@router.post(
    "/documents/submit",
    response_model=Result[KnowledgeDocumentSubmitResponse],
    summary="提交知识库文件入库任务",
)
def submit_knowledge_document(
    request: KnowledgeDocumentSubmitRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[KnowledgeDocumentSubmitResponse]:
    """关联上传文件并提交 PostgreSQL 入库任务。"""
    return Result.success(knowledge_management_service.submit_document(db, request))


@router.post(
    "/documents/search",
    response_model=Result[list[KnowledgeDocumentResponse]],
    summary="查询知识库文档列表",
)
def search_knowledge_documents(
    request: KnowledgeDocumentSearchRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[list[KnowledgeDocumentResponse]]:
    """按照知识库、索引状态和文件名查询文档。"""
    return Result.success(knowledge_management_service.search_documents(db, request))


@router.post(
    "/documents/detail",
    response_model=Result[KnowledgeDocumentResponse],
    summary="查询知识库文档详情",
)
def get_knowledge_document(
    request: KnowledgeDocumentQueryRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[KnowledgeDocumentResponse]:
    """根据 knowledge_id 和 file_id 查询文档索引详情。"""
    return Result.success(
        knowledge_management_service.get_document(
            db, request.knowledge_id, request.file_id
        )
    )


@router.post(
    "/documents/reindex",
    response_model=Result[KnowledgeDocumentSubmitResponse],
    summary="重新构建知识库文档索引",
)
def reindex_knowledge_document(
    request: KnowledgeDocumentReindexRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[KnowledgeDocumentSubmitResponse]:
    """使用原切片配置或本次覆盖配置提交重建索引任务。"""
    return Result.success(knowledge_management_service.reindex_document(db, request))


@router.post(
    "/documents/delete",
    response_model=Result[KnowledgeDocumentDeleteResponse],
    summary="删除知识库文档",
)
def delete_knowledge_document(
    request: KnowledgeDocumentDeleteRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[KnowledgeDocumentDeleteResponse]:
    """提交异步删除任务，清理向量和 PostgreSQL 分块证据。"""
    return Result.success(
        knowledge_management_service.delete_document(
            db, request.knowledge_id, request.file_id, request.priority
        )
    )


@router.post("/ingestion/status", response_model=Result[IngestionRunResponse], summary="查询入库任务状态")
def get_ingestion_status(
    request: IngestionRunQueryRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[IngestionRunResponse]:
    """根据 run_id 查询排队、执行、重试和完成状态。"""
    run = ingestion_queue_service.get(db, request.run_id)
    if run is None:
        raise ValueError(f"入库任务不存在: {request.run_id}")
    return Result.success(IngestionRunResponse.model_validate(run, from_attributes=True))


@router.post(
    "/ingestion/search",
    response_model=Result[IngestionRunListResponse],
    summary="查询知识库任务列表",
)
def search_ingestion_runs(
    request: IngestionRunSearchRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[IngestionRunListResponse]:
    """分页查询入库、重建和删除任务运行记录。"""
    runs, total = ingestion_queue_service.search(
        db,
        knowledge_id=request.knowledge_id,
        file_id=request.file_id,
        operation=request.operation,
        status=request.status,
        page=request.page,
        page_size=request.page_size,
    )
    return Result.success(
        IngestionRunListResponse(
            total=total,
            page=request.page,
            page_size=request.page_size,
            items=[
                IngestionRunResponse.model_validate(run, from_attributes=True)
                for run in runs
            ],
        )
    )


@router.post("/ingestion/cancel", response_model=Result[IngestionRunResponse], summary="取消待执行任务")
def cancel_ingestion_run(
    request: IngestionCancelRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[IngestionRunResponse]:
    """取消尚未被 Worker 抢占的 pending 任务。"""
    run = ingestion_queue_service.cancel_pending(db, request.run_id)
    return Result.success(IngestionRunResponse.model_validate(run, from_attributes=True))


@router.post("/ingestion/retry", response_model=Result[IngestionRunResponse], summary="重新提交失败任务")
def retry_ingestion_run(
    request: IngestionRetryRequest,
    db: Session = Depends(get_postgres_engine),
) -> Result[IngestionRunResponse]:
    """把失败任务复制为新的待执行任务，原任务记录继续保留。"""
    run = ingestion_queue_service.retry_failed(db, request.run_id)
    return Result.success(IngestionRunResponse.model_validate(run, from_attributes=True))


@router.post("/split/preview", response_model=Result[SplitOutput], summary="预览文本切片")
def preview_split(request: SplitInput) -> Result[SplitOutput]:
    """直接切分一段文本，用于调试切片参数，不执行知识库入库。"""
    return Result.success(knowledge_service.split_text(request))


@router.post("/embedding/preview", response_model=Result[EmbeddingOutput], summary="预览文本向量")
async def preview_embedding(request: EmbeddingInput) -> Result[EmbeddingOutput]:
    """调用 Embedding 模型生成临时向量，不写入 Milvus。"""
    return Result.success(await knowledge_service.embed_text(request))


@router.post("/retrieval/search", response_model=Result[RetrievalOutput], summary="执行底层知识检索")
async def search_collections(request: RetrievalInput) -> Result[RetrievalOutput]:
    """按 Collection 执行底层检索，主要用于能力测试与内部工具调用。"""
    return Result.success(await knowledge_service.retrieve(request))
