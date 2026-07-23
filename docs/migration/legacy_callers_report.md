# Task 23 旧链路调用者报告

## 结论

Task 23 完成后，FastAPI、Streamlit Client、`ChatService`、V2 Harness 与依赖容器均不导入或注册旧 Agent、Legacy Adapter、旧 Tool、旧路由或旧 Facade。旧文件仍物理保留，但仅能从弃用入口或独立历史回归测试/脚本访问。

`scripts/scan_legacy_references.ps1` 对每一行命中动态分类；报告自身和迁移文档也会被计入，因此总数随审计材料更新。Task 23 验收时正常运行时禁止引用为 0。

## 分类规则

| 分类 | 含义 | Task 23 处理 |
| --- | --- | --- |
| `legacy-entry-retained` | 弃用的旧启动入口 | 保留文件，不属于正常启动命令；Task 24 再处理 |
| `legacy-module-retained` | ReactAgent、旧 Tool/路由或兼容 Harness | 保留文件，正常依赖容器不注册 |
| `independent-regression` | 显式离线新旧对比脚本 | 保留，只有开发者手工执行才加载兼容层 |
| `legacy-test-retained` | 历史基线或兼容层测试 | 保留历史证据，不属于 V2 startup 测试 |
| `test-or-guard` | API 契约测试或零调用守卫 | 保留；Task 23 新测试不导入旧模块 |
| `documentation` / `comment` | 历史说明、迁移计划或注释 | 无运行时影响；过时材料由后续文档收口 |
| `tooling-or-evidence` | 启动脚本中的 `frontend/streamlit_app.py` 等文本命中 | 当前 FastAPI/Streamlit Client 启动方式，非旧调用 |

## 文件级调用清单

| 引用文件 | 引用对象 | 分类 | 是否可从正常 Runtime 到达 | 处置 |
| --- | --- | --- | --- | --- |
| `app.py` | `agent.react_agent.ReactAgent` | legacy-entry-retained | 否 | 保留弃用入口，Task 24 候选 |
| `agent/react_agent.py` | 旧 Tool/Middleware、ReactAgent | legacy-module-retained | 否 | 保留，Task 24 候选 |
| `agent/tools/agent_tools.py` | 旧 `RecipeQueryRouter` | legacy-module-retained | 否 | 保留；不得删除底层 RAG/Graph |
| `recipe_assistant/agents/harness.py` | `LegacyReactAgentAdapter`、`RecipeAgentHarness` | legacy-module-retained | 否 | 保留兼容文件，容器已解除注册 |
| `scripts/compare_legacy_vs_v2.py` | 旧路由与 Legacy Adapter | independent-regression | 否 | 唯一显式离线对比路径之一 |
| `tests/baseline/test_react_agent_baseline.py` | ReactAgent | legacy-test-retained | 否 | 保留历史基线数据与测试 |
| `tests/baseline/test_query_router_baseline.py`、`test/test_query_router.py` | 旧路由 | legacy-test-retained | 否 | 保留旧路由基线 |
| `tests/unit/test_harness.py` | Legacy Adapter/兼容 Harness | legacy-test-retained | 否 | 保留兼容契约证据 |
| `tests/integration/test_chat_service.py`、`tests/e2e/test_chat_api.py` | 兼容 Harness Fake | test-or-guard | 否 | 既有测试夹具，不被应用启动加载；后续随兼容层删除迁移 |
| `tests/unit/test_no_legacy_import.py`、`tests/integration/test_v2_startup_without_legacy.py`、`tests/e2e/test_v2_default_path.py` | 禁止模块名称 | test-or-guard | 否 | 负向断言，不执行旧 Agent |
| `tests/contract/test_openapi_contract.py` | 前端禁用字符串 | test-or-guard | 否 | API-only 边界断言 |
| `scripts/start_streamlit.ps1`、`scripts/smoke_windows.ps1` | `frontend/streamlit_app.py` | tooling-or-evidence | 是，新入口 | 文本匹配 `app.py`，实际启动的是 API Client |
| `README.md`、`docs/**/*.md`、迁移清单/执行手册 | 旧类名、文件名、历史状态 | documentation | 否 | 保留审计记录；当前说明已更新 |
| `scripts/scan_legacy_references.ps1` | 扫描模式本身 | tooling-or-evidence | 否 | 零调用门禁 |

## 正常运行时替代链路

```text
frontend/streamlit_app.py
  -> FastAPI /api/chat/stream
  -> ApiContainer
  -> ChatService (ChatHarness Protocol)
  -> MultiExpertHarness (V2 only)
  -> RecipeAgentRuntime / RecipeCoordinator / Experts
```

`ApiContainer` 不再构造 Legacy Adapter 或 Lazy Legacy Executor；`ChatService` 使用 Protocol，不再因类型标注加载旧 Harness；V2 失败返回明确失败结果，不会自动 fallback。

## 数据与后续边界

- 未删除或改写 SQLite、Chroma、BM25、Neo4j、营养目录及历史对比数据。
- 未删除 `app.py`、`agent/`、兼容 Harness 或旧测试。
- Task 24 只能依据本报告与零调用门禁分批删除，不得把底层 RAG/Graph 作为旧 Agent 一并删除。
