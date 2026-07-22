# 迁移清单

## 1. 目的与范围

本文把当前公开/事实接口映射到 V2 目标边界，并列出按风险排序的迁移问题。这里只建立清单，不创建目标实现。

## 2. 旧接口到目标接口映射

| 当前接口/入口 | 当前调用方 | 当前职责 | 后续目标接口 | 兼容方式 |
| --- | --- | --- | --- | --- |
| `app.py` | 浏览器/Streamlit | UI、会话状态、直接调用 Agent | `frontend/streamlit_app.py` → REST/SSE | 先保留入口；API 稳定后将内部调用替换为 API Client |
| `ReactAgent()` | `app.py`、手工脚本 | 创建 Agent、模型 Tool、内存 checkpoint | `RecipeAgentHarness` / `RecipeAgentRuntimeFactory` | 提供旧构造适配器，避免前期删除 |
| `ReactAgent.execute_stream(query, thread_id)` | Streamlit | 执行 Agent 并输出文本流 | `ChatService.stream_chat(ChatRequest)` / SSE Event | 适配旧参数到 DTO；旧方法保持到端到端回归完成 |
| `get_user_location()` | Agent | 公网 IP + 高德定位 | `WeatherService.resolve_user_location()` | Tool Adapter 调 Service；保留旧 Tool 名称与字符串结果适配 |
| `get_weather(city)` | Agent | 城市解析 + 高德天气 + JSON 字符串 | `WeatherService.get_current_weather(WeatherRequest)` | 新 Service 返回 Schema，旧 Tool 序列化为兼容字符串 |
| `rag_summarize(query)` | Agent/脚本 | 检索并生成自然语言答案 | `RetrievalService.retrieve(RetrievalRequest)` + 知识专家回答 | 先以 Adapter 调旧 Service；逐步拆分“检索”与“生成” |
| `route_recipe_query(query)` | Agent/调试 | LLM/规则选择 Graph、Vector、Hybrid | `RetrievalRouter.plan(RetrievalRequest)` | 路由下沉为 Service 内部能力；保留只读诊断适配器 |
| `smart_recipe_query(query)` | Agent | 路由、检索、生成统一入口 | `RecipeKnowledgeExpert` / `RecommendationExpert` → Tool Adapter → `RetrievalService` | 旧 Tool 先转调新 Service，稳定后停止新代码依赖它 |
| `graph_recipe_search(query_type, query_value)` | Agent/脚本 | 多种 Graph 查询的字符串分派 | `RecipeGraphAdapter` 的类型化方法 | 枚举和 Pydantic 参数替代自由字符串；旧分派函数作兼容层 |
| `hybrid_rag_summarize(query)` | Agent/脚本 | Hybrid 检索并生成答案 | `RetrievalService.retrieve(strategy=advanced_hybrid)` | 适配结果到旧字符串输出 |
| `RagSummarizeService.rag_summarize(query)` | Tool/脚本 | Vector 检索 + LLM 生成 | `RetrievalService` + `AiClient` | 先包装，后拆分生成职责 |
| `RagSummarizeService.retriever_docs(query)` | 内部/脚本 | 返回父块 `Document` | `RetrievalService.retrieve()` → `RetrievalResult` | 将 LangChain `Document` 规范化为 `RetrievalHit` |
| `HybridRagService.retrieve(...)` | Hybrid 内部/测试 | Graph/Vector/BM25/RRF | `RetrievalService.retrieve(RetrievalRequest)` | 保留旧类作为 Infrastructure Facade，新增 Schema 转换 |
| `HybridRagService.hybrid_summarize(...)` | Tool | 检索 + 生成 | `RetrievalService` + 专家/最终生成器 | 先包装旧行为，再拆职责 |
| `VectorStoreService.get_retriever()` | RAG Service | 暴露父子块 Retriever | `VectorRetrieverAdapter.retrieve()` | 容器持有单例 Adapter；旧方法保留过渡 |
| `ParentChildRetriever.invoke(...)` | RAG/Hybrid | Chroma 子块召回并回取父块 | `VectorRetrieverAdapter.retrieve(RetrievalRequest)` | 元数据标准化后转换为 `RetrievalHit` |
| `BM25RecipeRetriever.search(...)` | Hybrid | 关键词召回 | `Bm25RetrieverAdapter.retrieve()` | 容器启动时构建一次；旧返回 tuple 由适配器转换 |
| `rrf_fusion(...)` | Hybrid | 多路融合 | `RankingService.fuse()` | 保留纯函数，外围改用统一 Schema |
| `GraphRecipeRetriever.*` | Tool/Hybrid | 直接执行 Neo4j 查询 | `RecipeGraphAdapter` / `RetrievalService` | 容器管理 Driver；旧类暂时由 Adapter 包裹 |
| `Neo4jClient.execute_read/write()` | graph 模块 | 原始基础设施访问 | Infrastructure 内部 `Neo4jAdapter` | 不向 Agent/Tool/前端暴露；图谱构建脚本可保留管理入口 |
| `RecipeQueryRouter.route()` | `smart_recipe_query`、测试 | 检索层策略选择 | `RetrievalRouter.plan()` | 保留规则逻辑作为初始适配实现，统一输出 `RetrievalPlan` |

## 3. 目标检索数据契约映射

| 当前字段/形态 | 目标字段 | 迁移说明 |
| --- | --- | --- |
| `node_id` 或 `recipe_id` | `recipe_id` | ingestion 阶段一次性规范化，查询阶段停止双字段兼容 |
| `source` | `source_path` | 适配器读取旧字段并输出统一字段 |
| `Document.page_content` | `RetrievalHit.content` | 不让应用层依赖 LangChain `Document` |
| 隐式 rank / tuple score | `vector_score`、`bm25_score`、`graph_score` | 各召回器保留原始分数 |
| `fusion_score` metadata | `fused_score` | 成为类型化一级字段 |
| 无 rerank 字段 | `rerank_score` | 后续 ranking 任务实现；当前保持 `None` |
| 自由 `dict` filters | `RetrievalRequest` | 包含 recipe、食材包含/排除、工具、分类、top_k |
| 字符串答案 | `RetrievalResult` + 独立生成 | 检索 Service 不负责最终自然语言答案 |

## 4. 按风险排序的迁移问题

### P0：开始重构前必须保护

1. **工作树不是干净基线。** Task 00 开始前已有多处未提交的运行时代码修改；后续提交必须先由人工确认这些变更的归属，否则无法仅凭 Git 提交还原“当前行为”。
2. **导入即初始化重型资源。** `model.factory` 导入时加载聊天模型和 Embedding；Tool 模块导入时创建普通 RAG。缺少密钥或本地模型会导致 `ReactAgent` 连最小导入都失败。
3. **Hybrid 对 Neo4j 是硬依赖。** 创建 Hybrid Service 时连接并验证 Neo4j，BM25 也依赖 Neo4j 重构语料；Neo4j 不可用时没有 `Chroma + BM25` 的独立可用路径。
4. **前端直接依赖 Agent。** `app.py` 直接导入 `ReactAgent`，不符合最终 HTTP/SSE 边界；迁移时必须先建立 API 再切换前端，不能直接删除旧入口。
5. **缺少可执行的行为基线。** 当前 `test/` 多为手工脚本，缺少覆盖主链路成功/失败行为的稳定断言；Task 01 需要先建立测试与工程基线。

### P1：Service 与数据契约阶段优先处理

6. **检索与答案生成耦合。** 普通/Hybrid RAG Service 同时召回、拼上下文并调用 LLM，难以独立评测检索质量和实现模板化降级。
7. **资源生命周期分散。** Chroma、Neo4j Driver、BM25、模型分别由模块全局变量或请求级对象管理，没有统一 startup/shutdown。
8. **BM25 请求级重建。** 每个 Hybrid Service 都从 Neo4j读取全部菜谱、分词并重建索引，初始化成本高且会放大 Neo4j 故障。
9. **检索元数据不统一。** `recipe_id`/`node_id`、`source`、`difficulty`/`difficulty_text` 并存，RRF 还在缺少 chunk ID 时使用进程相关的 Python `hash()`。
10. **结构化路由信息丢失。** Hybrid 调用未显式传递路由器的包含/排除食材、工具和分类；排除食材也没有确定性强校验。
11. **Graph 候选没有形成统一过滤语义。** Vector/BM25 支持候选过滤能力，但当前 Hybrid 默认不传候选 ID，而是在融合排名阶段软提升。
12. **返回值缺少 Schema。** Tool 混用普通字符串、JSON 字符串、自由 `dict` 和 LangChain `Document`，调用方需要猜测结果形态。

### P2：运行可靠性和治理

13. **降级不完整。** 路由器有 LLM→规则兜底，但检索组件、Coordinator/专家（尚未实现）和最终生成没有分层 fallback 与 Trace。
14. **错误语义不统一。** 天气 Tool 部分吞异常并返回 `success=false` JSON，Graph/Hybrid 多数异常直接抛出，middleware 只记录后重抛。
15. **日志可能包含敏感输入。** middleware 记录完整 Tool 参数与最新消息；未来加入画像、过敏和位置后需结构化脱敏。
16. **短期记忆不可恢复。** `InMemorySaver` 与 Streamlit session 都是进程内状态，没有稳定 session/message ID 和 Repository。
17. **前端接收内部推理片段。** 当前流式实现会识别并输出 reasoning/`<think>` 内容；目标架构只应输出稳定状态事件和最终答案 token。
18. **配置来源不统一。** YAML 声明 `chat_api_key_env`，但工厂硬编码读取 `DEEPSEEK_API_KEY`；Neo4j 数据库配置同时存在 YAML 和环境变量默认值。

### P3：后续能力风险

19. **没有确定性硬约束服务。** 过敏、忌口、排除食材、厨具与时间约束尚未成为回答前的必经校验。
20. **缺少真实持久化和审计。** 用户画像、确认饮食记录、反馈、Trace、Bad Case 均未实现。
21. **没有评测闭环。** README 未提供当前仓库实测的路由、检索、延迟和错误基线，后续不得无评测声称提升。

## 5. 分阶段兼容策略

1. **冻结与测试：** 先为旧入口和各检索路径建立 smoke/regression 数据，不改变业务行为。
2. **资源容器：** 将现有模型、Embedding、Chroma、Neo4j 和 BM25 构造包装进容器，保留旧模块级别引用适配。
3. **统一 Schema：** 在 Adapter 边界把旧 `dict`/`Document` 转成 Retrieval DTO，不立即改写所有底层实现。
4. **Service Facade：** 新 `RetrievalService` 先委托现有 RAG/Graph/Hybrid 实现，之后逐路迁移。
5. **Tool Adapter：** 旧 Tool 名称转调 Service；新 Agent 只看到按角色授权的高层 Tool。
6. **API 与前端：** FastAPI/SSE 可用并通过回归后，Streamlit 改为 API Client；迁移期间保留根目录 `app.py`。
7. **清理：** 只有 V2 主链路、失败降级和 Windows 本地运行验收完成后，才删除旧 Agent/Tool 接口。

## 6. Task 00 明确不做

- 不修改上述接口行为。
- 不创建 FastAPI、多 Agent、数据库、反馈或 MCP。
- 不改变依赖版本、索引、Neo4j 数据或 Prompt。
- 不把盘点发现的问题提前修复。
