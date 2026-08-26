# minerU完整流程

## 1.提交解析任务
curl --request POST \
  --url http://192.168.10.194:18000/tasks \
  --header 'Accept: */*' \
  --header 'Accept-Encoding: gzip, deflate, br' \
  --header 'Connection: keep-alive' \
  --header 'User-Agent: PostmanRuntime-ApipostRuntime/1.1.0' \
  --header 'content-type: multipart/form-data' \
  --form 'files=@[object Object]' \
  --form lang_list=ch \
  --form backend=pipeline \
  --form parse_method=auto \
  --form formula_enable=true \
  --form table_enable=true \
  --form image_analysis=false \
  --form return_md=true

响应:
{
	"task_id": "421ccf4f-0b11-4826-aa51-d3ef52e8bebd",
	"status": "pending",
	"backend": "pipeline",
	"file_names": [
		"陈柱弛简历"
	],
	"created_at": "2026-08-26T07:34:46.969425+00:00",
	"started_at": null,
	"completed_at": null,
	"error": null,
	"status_url": "http://192.168.10.194:18000/tasks/421ccf4f-0b11-4826-aa51-d3ef52e8bebd",
	"result_url": "http://192.168.10.194:18000/tasks/421ccf4f-0b11-4826-aa51-d3ef52e8bebd/result",
	"queued_ahead": 0,
	"message": "Task submitted successfully"
}

## 2.拿第一步的task_id，进行轮询查询任务状态。
curl --request GET \
  --url http://192.168.10.194:18000/tasks/421ccf4f-0b11-4826-aa51-d3ef52e8bebd \
  --header 'Accept: */*' \
  --header 'Accept-Encoding: gzip, deflate, br' \
  --header 'Connection: keep-alive' \
  --header 'User-Agent: PostmanRuntime-ApipostRuntime/1.1.0'

响应：
{
	"task_id": "421ccf4f-0b11-4826-aa51-d3ef52e8bebd",
	"status": "completed",
	"backend": "pipeline",
	"file_names": [
		"陈柱弛简历"
	],
	"created_at": "2026-08-26T07:34:46.969425+00:00",
	"started_at": "2026-08-26T07:34:46.971653+00:00",
	"completed_at": "2026-08-26T07:35:05.246660+00:00",
	"error": null,
	"status_url": "http://192.168.10.194:18000/tasks/421ccf4f-0b11-4826-aa51-d3ef52e8bebd",
	"result_url": "http://192.168.10.194:18000/tasks/421ccf4f-0b11-4826-aa51-d3ef52e8bebd/result",
	"queued_ahead": 0
}

我们在这一步重点要看status的状态，有4种，如下：
pending	排队等待	继续轮询，并查看 queued_ahead
processing	正在解析	继续轮询
completed	解析成功	调用 /result 获取结果
failed	解析失败	停止轮询，读取 error

## 3.当查询任务的状态为completed时，通过下面接口获取minerU的解析结果。
curl --request GET \
  --url http://192.168.10.194:18000/tasks/421ccf4f-0b11-4826-aa51-d3ef52e8bebd/result \
  --header 'Accept: */*' \
  --header 'Accept-Encoding: gzip, deflate, br' \
  --header 'Connection: keep-alive' \
  --header 'User-Agent: PostmanRuntime-ApipostRuntime/1.1.0'

响应结果如下：
{
	"backend": "pipeline",
	"version": "3.4.5",
	"results": {
		"陈柱弛简历": {
			"md_content": "## 个人简历\n\n抵抗压力的最有效方法是实力，实力的来源是扎实的知识。\n\n## 基本信息\n\n姓 名 ：陈柱弛\n\n籍 贯 ：海南海口\n\n出生年月 ：2002.11\n\n电 话 ：17889884746\n\n政治面貌 ：共青团员\n\n邮 箱 ：2863101306@qq.com\n\n学 历 ：本科学士\n\n![](images/2c564b2e4abb5ba1e506f2d692f3e5e7f012a58ecb16e43079046d6554ee309e.jpg)\n\n## 教育背景\n\n2021-09 \\~ 2025-07\n\n海南科技职业大学\n\n软件工程（本科）\n\n## 技能证书\n\n 2023 年第三届中国 RPA+AI开发者大赛优秀奖；\n\n● 2023 年 1+x达梦数据库职业技能中级证书;\n\n 2023RPA+AI 创新创意挑战赛二等奖；\n\n2023 年通过计算机技术与软件专业技术资格（水平）考试中级“软件设计师”证书；\n\n## 核心亮点\n\nAI 全栈应用工程师 | 擅长将 RPA、大模型、自动化工具结合全栈技术，快速落地业务场景的智能系统。曾参与联通“数字员工”端到端交付：使用 RPA 实现 7×24 小时智能工单处理，智能通知，数据获取等，人力成本下降 70 %，业务时效提升 8 倍。曾担任智海王潮集团数字化转型与 AI 应用搭建主要技术开发，主导开发各种结合 Agent 系统，Web系统，Rag 系统等，实现降本增效。\n\n## 技能特长\n\nLLM 应用：\n\n\\- 熟练本地部署与 API 调用各种 LLM 模型，如 DeepSeek / Qwen / GPT（Ollama / LM Studio）。\n\n\\- 设计结构化 Prompt Engineering 与 Tool Calling，实现可控的业务级输出。\n\nRAG：\n\n\\- 使用 LangChain + FastAPI 集合向量数据库构建 RAG 系统。\n\n\\- 使用 PostgreSQL + PGVector 或 Elasticsearch 构建向量数据库。\n\nAgent：\n\n\\- 基于 LangChain，LangGraph 构建 Agent，实现复杂任务的拆解与执行。\n\n\\- 使用 FastApi-mcp 实现 MCP 工具编写。\n\n后端与系统工程：\n\n\\- 基于 FastAPI 构建高性能后端服务，落地 RESTful API、鉴权(JWT)。\n\n\\- MySQL / PostgreSQL 数据库设计与 Docker 容器化部署。\n\n自动化与前端：\n\n\\- RPA（弘玑 / 影刀）+ Agent 实现业务流程自动化+智能化。\n\n\\- Vue + Element Plus / Ant Design Vue 构建前端 web 页面和小程序。\n\n低代码平台：\n\n\\- 熟练使用 Dify / ComfyUI 进行工作流编排，并完成工程化集成与复用。\n\n## 实习经历\n\n2024-12 \\~ 2025-04\n\n海南云方信息技术有限公司(中国联通合作伙伴） 实习软件开发工程师\n\n· 主要负责联通相关的 RPA 机器人开发和维护，使用 Vue2 进行 Web前端页面和小程序的迭代；\n\n· 通过弘玑 RPA 编写数字员工，解决企业内机械化的工作内容，并部署上线供一线人员使用；\n\n· 日常维护 RPA机器人的运行情况，保证机器人的稳定运行。\n\n## 工作经历\n\n2025-06 \\~ 2025-12\n\n智海王潮传播集团\n\n全栈 AI 应用工程师\n\n· 担任集团数字化转型与 AI 应用搭建主要技术开发,主导开发各种结合 agent 的 Web 系统。\n\n· 使用 Ollama，LM Studio 部署各种 AI 大模型--DeepSeek，Qwen，Gpt-oss 等。\n\n· 使用 ComfyUI 和 Dify 搭建生图 / 生视频 / Agent 工作流，并结合进各系统中。\n\n· 使用 Vue，FastApi，langchain，langgraph 框架编写 Web 系统接入 rag 和 agent 并维护。\n\n· 使用影刀编写 RPA自动化机器人，解决企业内机械化的工作内容。\n\n· 使用 MySQL / PostgreSQL 作为数据库，使用 PGVector 或 Elasticsearch 作为向量数据库。\n\n## 项目经验\n\n2025-09 \\~ 2025-11\n\n智能知识库系统\n\n全栈 AI 应用工程师\n\n简介：面向企业的智能知识库平台，集成文件管理、RAG 与 Agent，实现知识的高效检索与智能问答。\n\n职责：AI 领域相关功能开发，前端开发，数据库设计。\n\n功能亮点：\n\n• 在智能助手页面可以直接使用网盘中的资源，快速的和 AI 进行对话。\n\n• 文件一键整理功能，一键将目录下的文件按照需求进行分类。\n\n• 实现了 agentic rag，在对话过程中，AI 可以自主的执行向量检索，获取信息回答用户。\n\n技术亮点：\n\n• 后端：使用 FastAPI 和 LangChain，LangGraph 框架实现了 AI 领域的功能，实现了 AI 对话，\n\nAgentic RAG，和文件自动整理，一键上传知识库等 AI 领域相关功能。\n\n数据库使用 Mysql，postgreSql。向量数据库使用 PGvector(postgreSql 的向量扩展)。\n\n• 前端：使用 Vue3 搭配 Ant Design Vue 和 Element Plus 组件库来进行开发。\n\n2025-07 \\~ 2025-09\n\n智能投标管理系统\n\n全栈 AI 应用工程师\n\n简介：面向企业的智能招投标管理平台，结合 RPA 与大模型能力，实现标讯自动采集、智能分析与投标辅助决策。\n\n职责：负责系统整体前后端开发，自动化程序开发，数据库设计。\n\n功能亮点：\n\n• 基于 RPA 自动采集多来源标讯数据，减少人工信息收集成本。\n\n• 引入 AI 对标讯内容进行语义分析，生成投标可行性评估与建议。\n\n• 集成 Agent 对话助手，基于 Text2SQL 实现 Agent 自主查询数据库并返回业务结果。\n\n• 设计完整的拟投标流程，并结合钉钉进行及时通知，避免撞标情况的出现。\n\n技术亮点：\n\n• 数据获取：使用影刀 RPA + Dify 工作流实现标讯自动采集与 AI 分析，结果通过 API 入库 MySQL。\n\n• 后端：基于 FastAPI 构建业务系统，并结合 LangChain，LangGraph 实现 Agent 聊天助手。\n\n• 前端：使用 Vue2 全家桶 + Element Plus 构建管理后台。\n\n• 数据库：使用 MySQL 进行业务数据存储与查询。"
		}
	}
}