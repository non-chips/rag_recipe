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
| 隐式 Bad Case | 旧日志人工排查 | `BadCaseService` + 隐式信号/审批状态机 | `bad_case_001` | 待验证 | 是：V2 新增可审计闭环 | 管理路由尚未注册默认 API |
| Tool 权限与审计 | `monitor_tool` 日志中间件 | `ToolGovernance` + `ToolTraceMiddleware` + Trace Repository | `tool_governance_001` | 待验证 | 是：V2 权限更严格 | 需核对失败事件与用户可见错误 |
| HTTP/SSE | 根 Streamlit 直调 Python Agent | FastAPI `/api/chat/stream` + SSE + API-only Streamlit | `api_sse_001`、`sse_disconnect_001` | 待验证 | 是：明确进程边界 | 前端已仅调用 API；后端非 SIMPLE 仍延迟加载旧 Agent |

## Task 21 前置结论

- 功能归属已经明确，但尚不能据此删除任何旧实现。
- `RecipeCoordinator` 未接入默认 Chat Runtime 是当前最大的等价性缺口。
- 反馈与 Bad Case 管理路由未注册默认 API，属于发布契约缺口。
- Task 21 必须输出功能、数据一致性、检索质量和性能证据；本表不替代对照报告。
