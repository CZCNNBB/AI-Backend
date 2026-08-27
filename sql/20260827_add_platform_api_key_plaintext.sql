-- 为已经执行过业务平台隔离迁移的开发数据库增加 API Key 明文字段。
--
-- 说明：已有 Hash 无法反推出原始 API Key。当前项目仍处于开发阶段，
-- 本脚本会删除旧的 API Key 记录；执行后请在业务平台管理页重新签发。

BEGIN;

ALTER TABLE platform.business_platform_api_keys
ADD COLUMN IF NOT EXISTS api_key VARCHAR(255);

-- 旧记录没有可恢复的明文。直接清理，避免管理端误以为可以自动使用。
DELETE FROM platform.business_platform_api_keys
WHERE api_key IS NULL;

ALTER TABLE platform.business_platform_api_keys
ALTER COLUMN api_key SET NOT NULL;

COMMENT ON TABLE platform.business_platform_api_keys IS
'平台调用 API Key，内网模式保存明文并同时保留鉴权哈希。';

COMMENT ON COLUMN platform.business_platform_api_keys.api_key IS
'内网管理调试使用的完整 API Key，请勿写入日志。';

COMMIT;
