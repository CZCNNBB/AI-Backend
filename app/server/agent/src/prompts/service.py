from typing import Any


class AgentPromptService:
    """Agent 提示词渲染服务。"""

    def render_system_prompt(self, template: str, variables: dict[str, Any] | None = None) -> str:
        """
        渲染系统提示词。

        Args:
            template: 系统提示词模板。
            variables: 编排层或业务层注入的变量。

        Returns:
            渲染后的系统提示词。
        """
        if not variables:
            return template
        rendered = template
        for key, value in variables.items():
            rendered = rendered.replace("{{" + key + "}}", str(value))
        return rendered
