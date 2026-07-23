# 旧链路与 V2 能力对照矩阵

> Task 20 只建立替代关系和验证入口，不宣称新旧链路已经等价。所有“待验证”项必须在 Task 21 使用同一数据集分别执行后才能改为“是”。

## 判定规则

- **功能归属**：V2 中存在明确的 Service、Expert、Repository 或 API 契约。
- **等价性**：Task 21 对照验证前统一标记为“待验证”。
- **有意差异**：安全、持久化和职责边界方面的设计变化可以保留，但必须在对照报告中说明。
- **硬门槛**：过敏原、排除食材、会话/反馈/饮食数据一致性不得以“有意差异”为由降低要求。

## 功能对照

| 业务能力 | 旧入口/实现 | V2 归属 | Task 21 验证用例 | 是否等价 | 差异是否有意 | 当前证据与风险 |
| --- | --- | --- | --- | --- | --- | --- |
| 简单问候与能力说明 | `ReactAgent` | `BusinessRouter` + `SimpleChatService` | `greeting_001`、`capability_001` | 待验证 | 是：SIMPLE 不调用 LLM/Tool | 已有 SIMPLE 单元测试；需做新旧输出语义对照 |
| 精确菜谱做法问答 | `smart_recipe_query` → `rag_summarize` | `RecipeKnowledgeExpert` + `RetrievalService` | `recipe_qa_001` | 待验证 | 是：V2 要求证据化结果 | Coordinator 尚未接入默认 Chat Runtime |
| 菜谱结构化事实 | `graph_recipe_search` / `RecipeQueryRouter` | `RecipeKnowledgeExpert` + `RetrievalRouter` + Neo4j Adapter | `recipe_fact_001` | 待验证 | 否 | Neo4j 可禁用，必须验证降级来源 |
| 模糊菜谱检索 | 旧 Vector/Hybrid Facade | `RetrievalService` + Chroma/BM25/RRF | `recipe_fuzzy_001` | 待验证 | 是：统一 Retrieval DTO | 需核对召回率及证据元数据 |
| 食材组合推荐 | `ReactAgent` + `smart_recipe_query` | `RecipeRecommendationExpert` + `RecommendationService` | `rec_001` | 待验证 | 是：先验证硬约束再排序 | 默认 API 仍走旧执行器 |
| 厨具、时间、人数限制 | Prompt + 旧 Tool | `ConstraintService` + `RecipeRecommendationExpert` | `constraint_001` | 待验证 | 是：结构化约束 | 自然语言约束提取仍为保守规则 |
| 排除食材 | Prompt + `RecipeQueryRouter` | `ConstraintService` | `exclude_001` | 待验证 | 否 | P0，必须 100% 通过 |
| 过敏原限制 | 主要依赖 Prompt | `ProfileService` + `ConstraintService` | `allergen_001` | 待验证 | 是：V2 将其提升为硬约束 | P0，必须 100% 通过 |
| 天气推荐 | `get_user_location` + `get_weather` + `smart_recipe_query` | `WeatherService` + `RecipeRecommendationExpert` | `weather_001`、`weather_degrade_001` | 待验证 | 是：天气失败应显式降级 | 旧高德实现仍在旧 Tool 文件，具体 provider 迁移待确认 |
| 营养查询与规划 | 无完整独立专家，部分由旧 Agent 自由生成 | `NutritionPlanningExpert` + `NutritionService` + `NutritionCatalog` | `nutrition_001`、`nutrition_missing_001` | 待验证 | 是：V2 只使用结构化营养目录 | 营养目录覆盖率可能不足 |
| 多专家协作 | 旧 Agent 自主选择 Tool | `RecipeCoordinator` + `ExpertRegistry` + Blackboard | `complex_001` | 待验证 | 是：V2 使用确定性编排 | Runtime 已实现但未接默认 Harness/API |
| 会话历史 | LangGraph `InMemorySaver(thread_id)` | SQLite `ChatSession`/`Message` + `MemoryService` | `session_001`、`restart_001` | 待验证 | 是：V2 跨进程持久化 | 默认 FastAPI 已写 SQLite，但回答仍可能来自旧 Agent |
| 用户偏好 | 旧 Prompt/会话上下文 | `UserProfile` + `ProfileService` | `profile_001` | 待验证 | 是：结构化持久化 | 需验证偏好真正进入专家上下文 |
| 饮食记录 | 无稳定结构化事实来源 | `recipe_interactions` + `MealHistoryService` | `meal_query_001`、`meal_consume_001` | 待验证 | 是：区分 QUERY/COOK/CONSUME | 数据语义是 P0 一致性门槛 |
| 显式反馈 | 无正式能力 | `FeedbackService` + SQLite Repository | `feedback_001` | 待验证 | 是：V2 新增能力 | 路由已实现但默认 API 尚未注册 |
| 隐式 Bad Case | 旧日志人工排查 | `BadCaseService` + 隐式信号/审批状态机 | `bad_case_001` | 是（V2 新能力） | 是：V2 新增可审计闭环 | Service 与默认管理 API 契约均通过 |
| Tool 权限与审计 | `monitor_tool` 日志中间件 | `ToolGovernance` + `ToolTraceMiddleware` + Trace Repository | `tool_governance_001` | 待验证 | 是：V2 权限更严格 | 需核对失败事件与用户可见错误 |
| HTTP/SSE | 根 Streamlit 直调 Python Agent | FastAPI `/api/chat/stream` + SSE + API-only Streamlit | `api_sse_001`、`sse_disconnect_001` | 待验证 | 是：明确进程边界 | 前端已仅调用 API；后端非 SIMPLE 仍延迟加载旧 Agent |

## Task 21 前置结论

- 功能归属已经明确，但尚不能据此删除任何旧实现。
- `RecipeCoordinator` 未接入默认 Chat Runtime 是当前最大的等价性缺口。
- 反馈与 Bad Case 管理路由已在 Task 21 修复中注册默认 API。
- Task 21 必须输出功能、数据一致性、检索质量和性能证据；本表不替代对照报告。

## Task 21 对照结果

对照数据集包含 20 项离线、确定性组件/契约探针。旧侧执行真实 `LegacyReactAgentAdapter` 和 `RecipeQueryRouter` 规则模式，以离线流式 Agent 替代外部 LLM/Tool；V2 侧执行真实 `BusinessRouter`、`RecipeAgentRuntime`、领域 Service、SQLite Repository 和 FastAPI OpenAPI 契约，以确定性检索/天气 Provider 替代外部服务。该结果可审计且可重复，但不是 DeepSeek、高德、Chroma 或 Neo4j 的线上质量/性能基准。

| 能力组 | 结果 | 等价性结论 | 证据/差异 |
| --- | --- | --- | --- |
| 简单聊天 | 通过 | 组件级等价 | SIMPLE Route 和非空回答通过；V2 有意绕过 LLM/Tool |
| 菜谱知识 | 通过 | 组件级等价 | 知识 Route、明确专家和检索来源通过；V2 Runtime 可直接执行 |
| 推荐与天气 | 通过 | 组件级等价 | 推荐 Route、天气成功/失败降级通过 |
| 排除食材与过敏原 | 2/2 通过 | P0 等价 | 不安全候选均被 `ConstraintService` 拒绝 |
| 多轮会话 | 通过 | V2 有意增强 | SQLite 恢复和消息顺序通过；旧侧仅为进程内 thread 语义 |
| 营养与数据不足 | 2/2 通过 | V2 新能力通过 | 覆盖率 1.0 精确模式与 0.5 降级模式符合预期 |
| QUERY/CONSUME | 通过 | P0 数据一致 | QUERY 未进入确认饮食历史 |
| 显式反馈 Service | 通过 | V2 新能力通过 | 重复 LIKE 幂等且只产生一行；默认 API 路由已注册 |
| Bad Case Service | 通过 | V2 新能力通过 | 工具失败 + 空检索生成待审核候选；默认管理路由已注册 |
| 检索降级 | 通过 | 组件级等价 | Graph/BM25 失败时 Chroma 命中且 `fallback_used=true` |
| API 契约 | 3/3 通过 | Task 21 契约等价 | Chat SSE、反馈和 Bad Case 管理路由均已注册 |
| V2 Runtime 直接调用 | 通过 | P1 通过 | `RecipeAgentRuntime` + Coordinator 可独立执行并产出 `RESPONSE_PLAN` |
| 默认 Runtime 预切换状态 | 符合阶段预期 | 不计入 Task 21 P1 | 仍为 `LazyLegacyExecutor`，由 Task 22 负责切换 |

汇总：20/20 通过；P0 为 7/7，P1 为 12/12，API 契约和数据一致性通过率均为 100%。完整逐项证据见 `reports/legacy_v2_parity_report.json`，延迟 P50/P95 和调用次数见 `reports/legacy_v2_performance_report.json`。

### Task 22 预切换事项

1. 默认非 SIMPLE 请求仍注入 `LazyLegacyExecutor`；这是 Task 22 要执行的切换动作，不是 Task 21 等价性失败。
2. Task 22 需要完成 Coordinator Runtime 的生产依赖装配、Harness 输出适配和显式回滚开关。
3. 切换后必须重新运行本数据集、完整回归和 Windows Smoke Test。

Task 21 的 P0/P1 与 API/数据门禁均已达到 100%，具备进入 Task 22 的技术前置条件。
