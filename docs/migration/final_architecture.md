# V2 最终架构

## 运行链路

```text
Streamlit API Client
  -> FastAPI REST / SSE
  -> ApiContainer / ApiApplicationService
  -> ChatService + SQLite Memory/Profile/Trace
  -> MultiExpertHarness (V2 only)
  -> BusinessRouter
  -> RecipeAgentRuntime / RecipeCoordinator / Blackboard
  -> Knowledge / Recommendation / Nutrition Experts
  -> ToolRegistry + Governance + Trace
  -> Retrieval / Weather / Nutrition / Constraint Services
```

正常运行时不存在 legacy、shadow 或自动旧链路 fallback。前端不导入后端业务
模块，所有交互通过 FastAPI API/SSE。

## 数据与基础设施

| 边界 | 实现 | 状态 |
| --- | --- | --- |
| 业务事实 | SQLite Repository、Alembic Schema | 会话、消息、用户、反馈、Bad Case、Trace、饮食记录 |
| 语义检索 | Chroma + 本地 BGE embedding | 保留；Task25 只读确认 17 个文件 |
| 关键词检索 | BM25 + Markdown/快照文档源 | 保留；不依赖 Neo4j 生命周期 |
| 图检索 | Neo4j Adapter | 默认关闭；Adapter 与重建源保留 |
| 多路融合 | RRF | 保留在 RetrievalService 基础设施 |
| 营养 | NutritionService + JSON Catalog | 结构有效；当前目录条目为 0，需后续导入真实数据 |
| 天气 | WeatherService + 可选 AMap Provider | 失败显式降级，不阻断安全推荐 |

## 核心约束

- development、test、production 均只接受 V2 Runtime。
- 排除食材与过敏原在推荐排序前执行硬过滤。
- `QUERY`、`COOK`、`CONSUME` 是不同事件；`QUERY` 不进入确认饮食历史。
- Bad Case 自动发现与开发者审批分离，所有状态变化保留审计记录。
- Tool 权限、确认、失败和 Trace 统一经过治理边界。
- 数据目录和索引不随旧业务代码删除。

## 运维入口

- API：`scripts/start_api.ps1`
- Streamlit Client：`scripts/start_streamlit.ps1`
- 环境检查：`scripts/check_environment.ps1`
- 15 类最终 Smoke：`scripts/final_smoke_test.ps1`
- 离线评测：`scripts/run_evaluation.py`

历史删除文件、保留模块与逐批回滚点见
`docs/migration/removed_legacy_files.md`。
