"""模型资源配置校验测试。"""

import unittest

from pydantic import ValidationError

from app.server.agent.src.model.schemas import ModelConfigUpsertRequest
from app.server.agent.src.schemas.request import ModelRuntimeOptions


class ModelConfigSchemaTestCase(unittest.TestCase):
    """验证不同模型类型的公共配置约束。"""

    def test_embedding_model_requires_dimension(self) -> None:
        """Embedding 模型必须在 extra_config 中提供向量维度。"""
        with self.assertRaises(ValidationError):
            ModelConfigUpsertRequest(
                model_code="embedding-test",
                model_name="provider-embedding",
                model_type="embedding",
                base_url="http://127.0.0.1:8000/v1",
            )

    def test_embedding_model_accepts_positive_dimension(self) -> None:
        """合法的 Embedding 模型配置应保留维度。"""
        request = ModelConfigUpsertRequest(
            model_code="embedding-test",
            model_name="provider-embedding",
            model_type="embedding",
            base_url="http://127.0.0.1:8000/v1",
            extra_config={"dimension": 1024},
        )
        self.assertEqual(request.extra_config["dimension"], 1024)

    def test_embedding_model_rejects_invalid_batch_size(self) -> None:
        """Embedding 批大小必须限制在服务允许的安全范围内。"""
        with self.assertRaises(ValidationError):
            ModelConfigUpsertRequest(
                model_code="embedding-test",
                model_name="provider-embedding",
                model_type="embedding",
                base_url="http://127.0.0.1:8000/v1",
                extra_config={"dimension": 1024, "batch_size": 0},
            )

    def test_model_runtime_defaults_are_shared(self) -> None:
        """模型调用默认超时和重试次数应由公共常量统一提供。"""
        options = ModelRuntimeOptions()
        self.assertEqual(options.timeout_seconds, 60)
        self.assertEqual(options.max_retries, 2)


if __name__ == "__main__":
    unittest.main()
