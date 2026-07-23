# Task 24 已删除旧业务文件

Task 24 按依赖顺序完成物理删除。每批删除后均执行完整 pytest、Ruff 和
compileall；业务数据、索引与底层检索实现未删除。

## 提交与回滚点

| 批次 | 提交 | 删除内容 | V2 替代 | 验收 | 单批回滚 |
| --- | --- | --- | --- | --- | --- |
| 1 | `1bc12fb` | `app.py` 旧直连前端；README 旧启动说明 | `frontend/streamlit_app.py` → FastAPI/SSE | 158 passed；Ruff/compileall 通过 | `git revert 1bc12fb` |
| 2 | `7bc35fd` | `agent/routing/*`、`agent/tools/*` | `BusinessRouter`、`RetrievalRouter`、ToolRegistry、领域 Tool | 158 passed；Ruff/compileall 通过 | `git revert 7bc35fd` |
| 3 | `fabd86b` | `agent/react_agent.py`、旧 ReAct 主 Prompt、系统 Prompt 配置 | `MultiExpertHarness`、Coordinator、Experts、SQLite 会话 | 158 passed；Ruff/compileall 通过 | `git revert fabd86b` |
| 3b | `582de66` | `model/factory.py` 的旧聊天/embedding 混合工厂 | V2 Chat ResourceContainer；embedding 构造下沉至 VectorStore | 158 passed；Ruff/compileall 通过 | `git revert 582de66` |
| 4 | `cb18be4` | `recipe_assistant/agents/harness.py` 中兼容 Harness/Adapter | V2 `MultiExpertHarness` + `ChatHarness` Protocol | 158 passed；Ruff/compileall 通过 | `git revert cb18be4` |
| 5 | `1ec3a7a` | `rag/rag_service.py`、生成式 `hybrid_summarize`、旧 RAG Prompt/加载器 | `RetrievalService` + Expert/Renderer；Hybrid 模块只保留检索 | 158 passed；Ruff/compileall 通过 | `git revert 1ec3a7a` |

多批整体回滚必须按逆序执行：`582de66` → `1ec3a7a` → `cb18be4` →
`fabd86b` → `7bc35fd` → `1bc12fb`。其中 3b 的提交时间晚于第5批，因此按
Git 拓扑优先回滚。

## 删除文件明细

- 入口：`app.py`
- 旧路由：`agent/routing/__init__.py`、`agent/routing/query_router.py`
- 旧 Tool：`agent/tools/agent_tools.py`、`agent/tools/middleware.py`
- 旧 Agent：`agent/react_agent.py`
- 兼容层：`recipe_assistant/agents/harness.py`
- 回答 Facade：`rag/rag_service.py`
- 旧模型工厂：`model/factory.py`
- 旧 Prompt：`prompts/main_prompt.txt`、`prompts/rag_summarize.txt`
- 旧 Prompt 配置/加载器：`config/prompts.yml`、`utils/prompt_loader.py`

## 明确保留

| 保留模块/资产 | 原因 |
| --- | --- |
| `rag/vector_store.py`、`storage/chroma_db/` | Chroma 语义检索、父子块与 embedding 基础设施 |
| `rag/retrieval/bm25_retriever.py`、`document_source.py` | BM25 独立召回与文档来源 |
| `rag/retrieval/fusion.py` | RRF 多路结果融合 |
| `rag/retrieval/retrieval_router.py` | V2 检索基础设施路由，不是已删除的业务路由 |
| `rag/hybrid_rag_service.py::retrieve` | 保留图、向量和 BM25 的组合检索，不再生成回答 |
| `rag/ingestion/metadata_normalizer.py` | V2 检索元数据规范 |
| `graph/graph_retriever.py`、`graph/neo4j_client.py` | 可选 Neo4j 检索 Adapter |
| `graph/recipe_parser.py`、`graph/graph_builder.py`、`graph/build_graph_store.py` | Neo4j 数据可重建路径 |
| `recipe_assistant/services/weather.py` | V2 推荐专家天气边界 |
| `model/embeddingmodels/` | 本地 embedding 模型资产 |
| SQLite、Chroma、BM25、Neo4j、菜谱和营养数据 | 业务事实与可重建索引，不属于旧业务代码 |

## 测试迁移

没有删除测试或降低断言。旧路由、ReactAgent、兼容 Harness 和回答 Facade
测试分别迁移到 BusinessRouter、V2 Harness、ChatHarness Protocol 和
RetrievalService；Task21 parity 保留冻结旧侧观察数据，但不再导入已删除模块。
