# 当前架构（Task 19 源码核对版）

本文记录 2026-07-22 工作区源码的实际状态，不声明尚未测量的线上效果。

## 运行边界

```text
Streamlit frontend/streamlit_app.py
        │ HTTP + SSE
        ▼
FastAPI recipe_assistant.main:app
        │
        ├─ /actuator/health
        ├─ /api/chat、/api/chat/stream
        └─ /api/resources
              │
              ▼
ApiContainer → Coordinator / Harness → 专家与 Service
              │
              ├─ BusinessRouter（业务路由）
              ├─ RetrievalService（Graph / Chroma / BM25，可降级）
              ├─ ConstraintService + RecommendationService
              ├─ NutritionService
              └─ SQLite 持久化与 Trace
```

默认主路由由 `recipe_assistant/api/router.py` 静态注册。反馈路由与 Bad Case
管理路由已有独立实现和测试，但截至本次核对尚未注册到默认 `api_router`，因此前端反馈
控件在默认启动方式下会收到 404。该差异是当前发布门禁风险，不在文档中隐藏。

## 资源与检索

- `ApiContainer` 在 FastAPI lifespan 中创建、启动和关闭，重资源延迟初始化。
- `RetrievalService` 统一 Graph、Chroma、BM25 的结果结构；任何后端失败都会写入
  `warnings` 并将 `fallback_used` 置为真。
- BM25 可独立注入或构建，不以 Neo4j 为数据源前置条件；旧 Hybrid 链路仍可同时使用
  Graph、Chroma 与 BM25。
- 营养计算只使用带来源、质量和版本的目录数据，不由模型臆造营养数值。

## 兼容层

- 根目录 `app.py` 仍是旧 Streamlit 直连 `ReactAgent` 入口，已弃用但未删除。
- `LazyLegacyExecutor` 仍会在新运行链失败或未配置时延迟导入 `ReactAgent`。
- 旧 `agent/`、`rag/hybrid_rag_service.py` 和 Graph 适配器仍被兼容调用或基线测试引用。
- 当前推荐入口是 `scripts/start_api.ps1` 与 `scripts/start_streamlit.ps1`。

## 验证边界

Task 19 离线评测直接调用现有业务 Service，并使用可计数的内存/离线替身隔离远端依赖。
它覆盖业务路由、检索、推荐、营养、反馈和 Bad Case，但不代表生产 LLM、远端数据库、
并发容量或网络延迟。完整数值见 `docs/final_migration_report.md`。
