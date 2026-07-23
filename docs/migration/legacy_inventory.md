# 旧 ReactAgent 资产与调用清单

> 盘点基线：`3af76831338fb22bec66fbeaf30b3d6e0ec4e4c1`（Task 19 后的 `main`）。处置状态仅是迁移计划，不授权在 Task 20 删除或移动文件。

## 当前运行时调用

```text
旧 Streamlit：app.py
  → agent.react_agent.ReactAgent
  → agent.tools.agent_tools
  → 天气 / RecipeQueryRouter / RagSummarizeService / HybridRagService / GraphRecipeRetriever

默认 FastAPI：recipe_assistant.main
  → ApiContainer.build_default
  → RecipeAgentHarness
  → SIMPLE: SimpleChatService
  → 非 SIMPLE: LazyLegacyExecutor
      → LegacyReactAgentAdapter
      → agent.react_agent.ReactAgent
```

因此当前状态不是“旧链路零调用”。`RecipeAgentRuntime`、`RecipeCoordinator` 和三专家已经存在，但未注入默认 `RecipeAgentHarness`/`ChatService`。

## 文件级处置清单

| 分类 | 文件/目录 | 当前调用者 | V2 替代或继续归属 | 计划处置 | 处置前置条件 |
| --- | --- | --- | --- | --- | --- |
| 旧入口 | `app.py` | 用户手工运行、README 旧说明 | `frontend/streamlit_app.py` → FastAPI | 删除（Task 24） | Task 22 默认切换、Task 23 零调用、前端 Smoke 通过 |
| 旧编排 | `agent/react_agent.py` | `app.py`、`LazyLegacyExecutor`、基线测试 | `BusinessRouter` + `RecipeAgentRuntime` + `RecipeCoordinator` + Experts | 删除（Task 24） | Coordinator 接入、Task 21 等价、Task 23 零调用 |
| 旧 Tool 聚合 | `agent/tools/agent_tools.py` | `ReactAgent` | 新 Tool Registry、领域 Service/Expert | 迁移后删除 | 先迁移天气 provider；确认所有 Facade 无调用者 |
| 旧 Tool 中间件 | `agent/tools/middleware.py` | `ReactAgent` | `ToolGovernance`、`ToolTraceMiddleware`、Trace Repository | 删除（Task 24） | 新链路审计/失败行为验证完成 |
| 旧业务/检索路由 | `agent/routing/query_router.py` | `smart_recipe_query`、旧测试 | `BusinessRouter` + `rag/retrieval/RetrievalRouter` | 删除（Task 24） | Task 21 路由对照通过且无运行时调用 |
| 兼容适配器 | `recipe_assistant/agents/harness.py::LegacyReactAgentAdapter` | `LazyLegacyExecutor`、单元测试 | 面向 Coordinator 的 V2 executor/runtime adapter | 删除（Task 24） | Task 22/23 后容器不再注册旧 executor |
| 兼容执行器 | `recipe_assistant/api/dependencies.py::LazyLegacyExecutor` | `ApiContainer.build_default` | V2 runtime executor | 删除（Task 24） | 默认 API 完成 V2 注入并通过观察门槛 |
| 旧 Agent Prompt | `prompts/main_prompt.txt` | `utils/prompt_loader.py` → `ReactAgent` | Experts/Skills 的结构化提示与行为约束 | 删除（Task 24） | `ReactAgent` 删除且无其他加载者 |
| Prompt 加载器 | `utils/prompt_loader.py` | 旧 Agent、旧 RAG Facade | Expert/Skill 配置边界 | 待确认 | `rag/rag_service.py` Facade 去除前仍需保留 |
| 旧 Vector 回答 Facade | `rag/rag_service.py` | 旧 Tool、基线/手工脚本 | `RetrievalService` + `RecipeKnowledgeExpert` | 删除 Facade，保留检索底层 | 静态零调用且答案生成职责已迁移 |
| 旧 Hybrid 回答 Facade | `rag/hybrid_rag_service.py::hybrid_summarize` | 旧 Tool | `RetrievalService` + 专家 | 迁移/拆分 | 只删除生成 Facade，不删除融合和检索逻辑 |
| 旧模型工厂 | `model/factory.py` | ReactAgent、旧路由 L2、旧 RAG、向量库 embedding | V2 可注入模型边界；embedding 仍可能复用 | 待确认/拆分 | 区分 ChatModel 旧依赖与 Chroma embedding 复用依赖 |
| 旧配置加载 | `utils/config_handler.py`、`config/*.yml` | RAG/Graph/旧 Agent | `recipe_assistant.core.config.Settings`，同时兼容底层检索 | 保留并逐步迁移 | V2 RetrievalService 仍间接依赖旧 RAG 配置 |
| 旧基线测试 | `tests/baseline/test_react_agent_baseline.py` | Pytest | Task 21 parity 数据集、Task 23 legacy 隔离测试 | 迁移后删除 | 先保留为下线证据，不得提前删除测试 |
| 旧路由测试 | `tests/baseline/test_query_router_baseline.py`、`test/test_query_router.py` | Pytest/手工执行 | BusinessRouter/RetrievalRouter 测试 | 迁移后删除 | Task 21 对照覆盖相同意图 |

## 必须保留的可复用底层模块

| 模块 | V2 调用证据 | 结论 |
| --- | --- | --- |
| `rag/vector_store.py`、`storage/chroma_db/` | `RetrievalService` 延迟创建 `VectorStoreService` | 保留；是 Chroma 向量检索和父子块索引实现 |
| `rag/retrieval/bm25_retriever.py` | `RetrievalService` 和 `ResourceContainer` | 保留；BM25 可由 Markdown/快照独立构建，不应绑定 Neo4j 生命周期 |
| `graph/graph_retriever.py`、`graph/neo4j_client.py` | `RetrievalService` 在 Neo4j 启用时使用 | 保留；作为可选图检索 Adapter |
| `rag/retrieval/fusion.py` | `RetrievalService` 使用 `rrf_fusion` | 保留；负责多路结果融合 |
| `rag/retrieval/retrieval_router.py` | `RetrievalService` 使用 | 保留；它是检索基础设施路由，不是旧业务路由 |
| `rag/ingestion/metadata_normalizer.py` | `RetrievalService` 使用 | 保留；统一检索文档契约 |
| `rag/retrieval/document_source.py` | BM25 文档来源 | 保留；支持 Markdown、快照和可选 Neo4j 来源 |
| `graph/recipe_parser.py`、`graph/graph_builder.py`、`graph/build_graph_store.py` | Neo4j 可重建路径 | 保留；用于恢复图数据 |
| `data/recipes/` | Chroma、BM25、Neo4j 的权威重建输入 | 保留并由 Git 归档分支保护 |
| `recipe_assistant/services/weather.py` | 推荐专家的天气上下文边界 | 保留；旧高德 provider 迁移完成前不能删除旧 Tool 文件 |

## 数据与索引资产

| 资产 | 当前路径/来源 | 性质 | Task 20 保护方式 |
| --- | --- | --- | --- |
| 会话、消息、用户、反馈、Trace、饮食记录 | `storage/recipe_assistant.db`（及可能的 `-wal`/`-shm`） | 唯一业务事实数据 | 停止进程后冷备份并生成 SHA-256 清单 |
| Chroma 向量库 | `storage/chroma_db/` | 可重建但重建成本高 | 目录级备份和逐文件校验 |
| 父文档快照 | `storage/parent_documents.json` | Chroma 父子块恢复资料 | 单独备份和校验 |
| 摄取辅助状态 | `storage/recipe_md5.text`、`storage/child_chunk_counts.csv` | 增量摄取/审计辅助 | 与索引一起备份 |
| 营养目录 | `data/nutrition/recipes.json` | V2 营养计算输入 | Git bundle + 配置快照 |
| 菜谱源文档 | `data/recipes/` | BM25/Chroma/Neo4j 权威重建源 | Git tag、归档分支和 Git bundle |
| Neo4j | 外部 Neo4j database（默认配置名 `neo4j`） | 外部状态 | 使用 `neo4j-admin database dump`；无 dump 时只具备可重建能力，不等同完整备份 |
| 配置 | `config/`、`.env.example`、可选 `.env` | 可重建参数/可能含密钥 | 配置快照；`.env` 仅显式开关备份并按敏感文件保护 |

## 静态扫描分类摘要

- **运行时调用**：`app.py`、`recipe_assistant/api/dependencies.py`、`agent/react_agent.py`、`agent/tools/agent_tools.py`。
- **测试调用**：`tests/baseline/test_react_agent_baseline.py`、`tests/unit/test_harness.py`、旧 QueryRouter 测试。
- **迁移文档/注释**：`docs/current_architecture.md`、`docs/final_migration_report.md`、`docs/migration_inventory.md`。
- **仍需保留**：所有被 `RetrievalService` 直接或延迟导入的 RAG/Graph 底层模块和对应数据。
- **可删除**：Task 20 阶段没有任何文件被批准删除；表中的删除结论都受后续任务门槛约束。
