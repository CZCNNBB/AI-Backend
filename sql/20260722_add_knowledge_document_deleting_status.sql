-- 为已有知识库表增加文档删除中的生命周期状态。
BEGIN;

ALTER TABLE knowledge.knowledge_documents
DROP CONSTRAINT IF EXISTS knowledge_documents_status_check;

ALTER TABLE knowledge.knowledge_documents
ADD CONSTRAINT knowledge_documents_status_check
CHECK (status IN ('pending', 'indexing', 'indexed', 'deleting', 'failed', 'deleted'));

COMMENT ON COLUMN knowledge.knowledge_documents.status IS
'索引状态：pending、indexing、indexed、deleting、failed、deleted';

COMMIT;
