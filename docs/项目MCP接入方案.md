# 项目 MCP 接入方案

## 📋 概述

本项目通过**适配器模式**实现了 MCP（Model Context Protocol）工具的接入，将远程 MCP 服务提供的工具转换为 LangChain 可用的 `StructuredTool`，使 Agent 能够调用外部服务能力。

---

## 🏗️ 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MCP 接入架构                                   │
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────┐ │
│  │  MCP Server  │    │  MCP Server  │    │  MCP Server  │    │   ...     │ │
│  │  (服务端)    │    │  (服务端)    │    │  (服务端)    │    │           │ │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘    └─────┬─────┘ │
│         │                   │                   │                  │       │
│         │ HTTP/WebSocket    │                   │                  │       │
│         ↓                   ↓                   ↓                  ↓       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    MCPProxyClient                                    │   │
│  │            (MCP协议客户端，负责通信)                                   │   │
│  └──────────────────────────┬─────────────────────────────────────────┘   │
│                             ↓                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     SimpleMCPAdapter                                 │   │
│  │           (MCP适配器，负责工具定义解析和创建)                            │   │
│  └──────────────────────────┬─────────────────────────────────────────┘   │
│                             ↓                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                   LangChainToolExecutor                              │   │
│  │           (LangChain工具执行器，负责创建StructuredTool)                 │   │
│  └──────────────────────────┬─────────────────────────────────────────┘   │
│                             ↓                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         Agent                                        │   │
│  │           (使用 MCP 工具 + 本地工具执行任务)                            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📦 核心组件

### 1. MCPProxyClient（MCP 协议客户端）

**作用**：负责与 MCP Server 通信，调用远程工具。

**关键方法**：
- `list_services()` - 获取所有可用服务列表
- `list_tools_async(service)` - 获取指定服务的工具列表
- `call_tool(service, tool_name, args)` - 调用远程工具（同步）
- `call_tool_async(service, tool_name, args)` - 调用远程工具（异步）

**配置**：
- `base_url`：MCP Server 地址（环境变量：`MCP_SERVER_API`）
- `token`：API 密钥

---

### 2. ToolExecutor（工具执行器基类）

**作用**：定义工具创建接口，抽象不同框架的工具创建逻辑。

```python
class ToolExecutor(ABC):
    @abstractmethod
    def create_tool(self, name: str, description: str, parameters: Dict[str, Any], 
                   execute_func: Callable, execute_async_func: Optional[Callable] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> Any:
        """创建框架特定的工具对象"""
        pass
```

**设计意图**：通过抽象层实现多框架适配，目前项目实现了 LangChain 版本，未来可扩展支持其他框架（如 AgentScope）。

---

### 3. SimpleMCPAdapter（MCP 适配器）

**作用**：核心适配器，负责解析 MCP 工具定义并创建工具。

**核心流程**：

```python
class SimpleMCPAdapter:
    def __init__(self, tool_executor: ToolExecutor, base_url: str = '', token: Optional[str] = None):
        self.tool_executor = tool_executor  # 框架特定的执行器
        self.base_url = base_url
        self.token = token
    
    async def build_tools_async(self, service: Dict[str, Any], client: Optional[Any] = None) -> List[Any]:
        """异步构建服务的所有工具"""
        # 1. 获取工具定义列表
        tool_defs = await actual_client.list_tools_async(service)
        
        # 2. 逐个创建工具
        for tool_def in tool_defs:
            tool = self.create_tool(tool_def, service, actual_client)
            tools.append(tool)
        
        return tools
```

**工具创建步骤**：

| 步骤 | 处理内容 |
|------|---------|
| 1 | 从工具定义中提取名称、描述、输入/输出 Schema |
| 2 | 处理参数注入配置（`injection_config`） |
| 3 | 创建同步/异步执行函数（调用 `MCPProxyClient.call_tool`） |
| 4 | 构建工具描述（包含注释信息） |
| 5 | 调用 `tool_executor.create_tool()` 创建框架特定工具 |

---

### 4. LangChainToolExecutor（LangChain 工具执行器）

**作用**：实现 `ToolExecutor` 接口，将 MCP 工具转换为 LangChain 的 `StructuredTool`。

**核心功能**：

```python
class LangChainToolExecutor(ToolExecutor):
    def create_tool(self, name, description, parameters, execute_func, execute_async_func, metadata):
        # 1. JSON Schema → Pydantic Model 转换
        args_schema = create_pydantic_model(parameters, f'{name}_Input')
        
        # 2. 包装执行函数，处理返回值格式
        def wrapped_execute_func(**kwargs):
            raw_result = execute_func(**kwargs)
            return self.convert_tool_result(raw_result)  # (content, artifact)
        
        # 3. 创建 StructuredTool
        return StructuredTool(
            name=name,
            description=description,
            args_schema=args_schema,
            func=wrapped_execute_func,
            coroutine=wrapped_execute_async_func,
            response_format='content_and_artifact',
            metadata=metadata,
        )
```

**关键技术点**：

| 技术点 | 说明 |
|--------|------|
| **JSON Schema → Pydantic** | 将 MCP 工具的 JSON Schema 参数定义转换为 Pydantic 模型 |
| **返回值格式** | `(content, artifact)` 元组，符合 LangChain 规范 |
| **同步/异步双支持** | 同时提供 `func` 和 `coroutine` 参数 |

---

### 5. MCPToolArgsInjector（参数注入器）

**作用**：处理 MCP 工具的参数注入配置，移除被注入的参数，给 LLM 提供无参工具，避免 LLM 输出对应参数，在调用时再补充注入参数。

**应用场景**：某些参数需要在运行时由系统自动注入（如用户 ID、会话 ID），不需要 LLM 决定。

---

## 🔧 使用方式

### 方式一：加载所有 MCP 服务的工具

```python
from utils.mcp_utils import build_all_mcp_tools_async
from mcp.mcp_adapter_langchain_simple import LangChainToolExecutor

# 创建工具执行器
executor = LangChainToolExecutor()

# 加载所有服务的 MCP 工具
mcp_tools = await build_all_mcp_tools_async(executor, token="your_api_key")

# 添加到 Agent
tools = [get_exchange_rate]  # 本地工具
tools.extend(mcp_tools)      # MCP 工具

agent = create_agent(model=model, tools=tools, system_prompt=prompt)
```

### 方式二：加载指定服务的工具

```python
from utils.mcp_utils import build_mcp_tools_async_with_service_list

# 定义服务列表
services = [
    {
        "service_id": "weather_service",
        "api_key": "weather_api_key",
        "base_url": "http://weather.mcp.server:8000",
        "tool_filter": ["get_weather"]  # 只加载特定工具
    },
    {
        "service_id": "search_service",
        "api_key": "search_api_key",
        "base_url": "http://search.mcp.server:8000"
    }
]

# 创建工具执行器
executor = LangChainToolExecutor()

# 加载指定服务的 MCP 工具
mcp_tools = await build_mcp_tools_async_with_service_list(executor, services)

# 添加到 Agent
tools = [get_exchange_rate]
tools.extend(mcp_tools)

agent = create_agent(model=model, tools=tools, system_prompt=prompt)
```

### 方式三：加载单个服务的工具

```python
from utils.mcp_utils import build_mcp_tools_async

# 定义单个服务
service = {
    "service_id": "weather_service",
    "api_key": "weather_api_key",
    "base_url": "http://weather.mcp.server:8000"
}

# 创建工具执行器
executor = LangChainToolExecutor()

# 加载单个服务的 MCP 工具
mcp_tools = await build_mcp_tools_async(executor, service)

# 添加到 Agent
tools = [get_exchange_rate]
tools.extend(mcp_tools)

agent = create_agent(model=model, tools=tools, system_prompt=prompt)
```

---

## 🔄 完整调用流程

```
用户请求："查询北京天气"
                ↓
┌─────────────────────────────────────────────────────────────────┐
│ Agent 决定调用工具                                             │
│   model.generate() → tool_calls: [{"name": "get_weather",      │
│                                    "args": {"city": "北京"}}]  │
└─────────────────────────────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────────────────────────────┐
│ LangChain 执行工具调用                                         │
│   tool.func(city="北京")                                       │
└─────────────────────────────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────────────────────────────┐
│ LangChainToolExecutor.wrapped_execute_func()                   │
│   1. 调用 MCP 执行函数                                         │
│   2. 转换返回值格式 (content, artifact)                        │
└─────────────────────────────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────────────────────────────┐
│ SimpleMCPAdapter.execute_func()                                │
│   1. 处理参数注入 (meta_intern_)                               │
│   2. 调用 MCPProxyClient.call_tool()                          │
└─────────────────────────────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────────────────────────────┐
│ MCPProxyClient.call_tool()                                     │
│   1. 构建请求                                                  │
│   2. 发送 HTTP/WebSocket 请求到 MCP Server                     │
│   3. 接收响应                                                  │
└─────────────────────────────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────────────────────────────┐
│ MCP Server 执行工具                                            │
│   1. 验证权限                                                  │
│   2. 执行业务逻辑                                              │
│   3. 返回结果                                                  │
└─────────────────────────────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────────────────────────────┐
│ 返回工具执行结果给 Agent                                       │
│   ToolMessage(content="北京天气：晴，25°C", artifact={...})     │
└─────────────────────────────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────────────────────────────┐
│ Agent 生成最终回答                                             │
│   model.generate() → "北京今天天气晴朗，气温25°C"               │
└─────────────────────────────────────────────────────────────────┘
```

---

## ⚙️ 配置说明

### 环境变量

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `MCP_SERVER_API` | MCP Server 基础地址 | - |

### 服务配置格式

```python
service = {
    "service_id": "service_identifier",  # 服务唯一标识
    "api_key": "your_api_key",           # API 密钥
    "base_url": "http://mcp.server:8000", # 服务地址
    "tool_filter": ["tool1", "tool2"],    # 可选：只加载指定工具
    "metadata": {"key": "value"},         # 可选：元数据，可设置默认参数值
}
```

### 工具定义格式（MCP Server 返回）

```python
tool_def = {
    "name": "get_weather",                    # 工具名称
    "description": "查询指定城市的天气情况",    # 工具描述
    "inputSchema": {                          # 输入参数 Schema
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名称"
            }
        },
        "required": ["city"]
    },
    "outputSchema": {...},                    # 输出 Schema
    "annotations": {...},                     # 注释信息
    "injection_config": {...},                # 参数注入配置
    "meta": {...}                             # 元数据
}
```

---

## 🎯 设计亮点

### 1. 适配器模式

```
MCP协议 → SimpleMCPAdapter → ToolExecutor → LangChain工具
                                    ↓
                              AgentScope工具（可扩展）
                                    ↓
                              其他框架工具（可扩展）
```

**优势**：
- ✅ 解耦 MCP 协议与具体框架
- ✅ 支持多框架适配
- ✅ 易于扩展新框架

### 2. 参数注入机制

```python
# MCP 工具定义中声明需要注入的参数
injection_config = {
    "user_id": {"source": "runtime", "key": "user_id"},
    "session_id": {"source": "runtime", "key": "session_id"}
}

# 注入器自动处理
MCPToolArgsInjector.inject(properties, injection_config)

# LLM 看到的工具是无参的（注入参数被移除）
# 运行时自动从 runtime 上下文中获取注入参数
```

**优势**：
- ✅ 简化 LLM 的工具调用（不需要关心注入参数）
- ✅ 运行时自动注入，保证安全性
- ✅ 参数来源灵活（runtime、config、env 等）

### 3. 返回值格式标准化

```python
def convert_tool_result(raw: Any) -> Any:
    """转换为 (content, artifact) 格式"""
    if isinstance(raw, dict):
        content = raw.get('content')
        data_val = raw.get('data', raw.get('result'))
        if data_val is not None:
            return str(data_val), raw  # 内容 + 原始数据
    
    return str(raw), raw
```

**优势**：
- ✅ 统一返回值格式
- ✅ `content` 用于 LLM 理解
- ✅ `artifact` 用于前端展示和引用

### 4. 工具过滤机制

```python
service = {
    "service_id": "weather_service",
    "tool_filter": ["get_weather", "get_forecast"]  # 只加载这两个工具
}
```

**优势**：
- ✅ 按需加载工具，减少 Agent 上下文大小
- ✅ 提高 LLM 工具选择准确性
- ✅ 降低 API 调用开销

---

## 🔗 相关文件

| 文件 | 说明 |
|------|------|
| [`mcp_utils.py`](file:///d:/work/HaiKong/AI/agent-engine/agent_engine/src/mcp_core/utils/mcp_utils.py) | MCP 工具构建工具函数 |
| [`mcp_adapter_simple.py`](file:///d:/work/HaiKong/AI/agent-engine/agent_engine/src/mcp_core/mcp/mcp_adapter_simple.py) | MCP 适配器基类 |
| [`mcp_adapter_langchain_simple.py`](file:///d:/work/HaiKong/AI/agent-engine/agent_engine/src/mcp_core/mcp/mcp_adapter_langchain_simple.py) | LangChain MCP 适配器 |
| [`mcp_tool_args_inject.py`](file:///d:/work/HaiKong/AI/agent-engine/agent_engine/src/mcp_core/mcp/mcp_tool_args_inject.py) | 参数注入器 |
| [`agent_creator.py`](file:///d:/work/HaiKong/AI/agent-engine/agent_engine/src/mcp_core/agent_creator.py) | MCP Agent 创建示例 |

---

## 📝 总结

| 组件 | 作用 |
|------|------|
| **MCPProxyClient** | MCP 协议通信客户端 |
| **ToolExecutor** | 工具执行器抽象接口 |
| **SimpleMCPAdapter** | MCP 工具解析和创建核心 |
| **LangChainToolExecutor** | LangChain 工具转换 |
| **MCPToolArgsInjector** | 参数注入处理 |

**核心流程**：
```
MCP Server → MCPProxyClient → SimpleMCPAdapter → LangChainToolExecutor → StructuredTool → Agent
```

**设计原则**：
- ✅ **适配器模式**：解耦协议与框架
- ✅ **依赖注入**：运行时参数注入
- ✅ **格式标准化**：统一返回值格式
- ✅ **按需加载**：工具过滤机制
