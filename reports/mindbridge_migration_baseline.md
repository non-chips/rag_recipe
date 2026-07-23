# MindBridge 协作运行时迁移基线

## 1. 范围与冻结目标

本基线对应任务包 01 的 P01-T01，冻结当前 V2 固定 Coordinator 的以下外部行为：

- 四类业务 Route 的固定任务模板；
- 依赖、优先级、预期 Artifact 与成本；
- 最终 Artifact 选择规则；
- FastAPI SSE 事件顺序；
- 迁移前后的相关自动化测试结果。

本任务包只增加后续协作调度所需的协议类型。默认 V2 仍使用固定任务循环和 `ExpertRegistry.resolve()`，不改变 API、SSE、RAG、营养、偏好、反馈或菜谱回答逻辑。

## 2. 固定 Route 任务模板

所有现有固定模板任务默认状态仍为 `PENDING`，默认成本均为 `1`。

### 2.1 `RECIPE_KNOWLEDGE`

| 顺序 | Task ID | Title | Capability | Depends On | Expected Artifact | Priority |
|---:|---|---|---|---|---|---|
| 1 | `knowledge.extract_constraints` | `ExtractConstraints` | `RECIPE_KNOWLEDGE` | — | `QUERY_CONSTRAINTS` | `NORMAL` |
| 2 | `knowledge.retrieve` | `RetrieveRecipeKnowledge` | `RECIPE_KNOWLEDGE` | `knowledge.extract_constraints` | `RECIPE_EVIDENCE` | `NORMAL` |
| 3 | `knowledge.evidence_check` | `EvidenceCheck` | `RECIPE_KNOWLEDGE` | `knowledge.retrieve` | `CONSTRAINT_VALIDATION` | `NORMAL` |
| 4 | `knowledge.response_plan` | `BuildResponsePlan` | `RECIPE_KNOWLEDGE` | `knowledge.evidence_check` | `RESPONSE_PLAN` | `NORMAL` |

### 2.2 `RECIPE_RECOMMENDATION`

无天气依赖时：

| 顺序 | Task ID | Title | Capability | Depends On | Expected Artifact | Priority |
|---:|---|---|---|---|---|---|
| 1 | `recommendation.extract_constraints` | `ExtractConstraints` | `RECIPE_RECOMMENDATION` | — | `QUERY_CONSTRAINTS` | `NORMAL` |
| 2 | `recommendation.preferences` | `LoadPreferences` | `RECIPE_RECOMMENDATION` | `recommendation.extract_constraints` | `USER_PREFERENCE_CONTEXT` | `NORMAL` |
| 3 | `recommendation.retrieve` | `RetrieveCandidates` | `RECIPE_RECOMMENDATION` | `recommendation.extract_constraints`, `recommendation.preferences` | `RECIPE_CANDIDATES` | `NORMAL` |
| 4 | `recommendation.rank` | `RankCandidates` | `RECIPE_RECOMMENDATION` | `recommendation.retrieve` | `RECIPE_CANDIDATES` | `NORMAL` |
| 5 | `recommendation.validate` | `ValidateConstraints` | `RECIPE_RECOMMENDATION` | `recommendation.rank` | `CONSTRAINT_VALIDATION` | `NORMAL` |
| 6 | `recommendation.response_plan` | `BuildResponsePlan` | `RECIPE_RECOMMENDATION` | `recommendation.validate` | `RESPONSE_PLAN` | `NORMAL` |

当 `requires_weather=true` 时，在约束提取后额外插入：

| 顺序 | Task ID | Title | Depends On | Expected Artifact |
|---:|---|---|---|---|
| 2 | `recommendation.weather` | `GetWeather` | `recommendation.extract_constraints` | `WEATHER_CONTEXT` |

此时 `recommendation.retrieve` 同时依赖：

- `recommendation.extract_constraints`
- `recommendation.weather`
- `recommendation.preferences`

### 2.3 `NUTRITION_PLANNING`

| 顺序 | Task ID | Title | Capability | Depends On | Expected Artifact | Priority |
|---:|---|---|---|---|---|---|
| 1 | `nutrition.meal_history` | `LoadConfirmedMealHistory` | `NUTRITION_PLANNING` | — | `MEAL_HISTORY` | `NORMAL` |
| 2 | `nutrition.summary` | `CalculateNutritionSummary` | `NUTRITION_PLANNING` | `nutrition.meal_history` | `NUTRITION_SUMMARY` | `NORMAL` |
| 3 | `nutrition.guidance` | `BuildNutritionGuidance` | `NUTRITION_PLANNING` | `nutrition.summary` | `NUTRITION_GOAL` | `NORMAL` |
| 4 | `nutrition.response_plan` | `BuildResponsePlan` | `NUTRITION_PLANNING` | `nutrition.guidance` | `RESPONSE_PLAN` | `NORMAL` |

### 2.4 `COMPLEX`

| 顺序 | Task ID | Title | Capability | Depends On | Expected Artifact | Priority |
|---:|---|---|---|---|---|---|
| 1 | `complex.nutrition_goal` | `NutritionPlanningExpert` | `NUTRITION_PLANNING` | — | `NUTRITION_GOAL` | `HIGH` |
| 2 | `complex.recipe_candidates` | `RecipeRecommendationExpert` | `RECIPE_RECOMMENDATION` | `complex.nutrition_goal` | `RECIPE_CANDIDATES` | `HIGH` |
| 3 | `complex.recipe_evidence` | `RecipeKnowledgeExpert` | `RECIPE_KNOWLEDGE` | `complex.recipe_candidates` | `RECIPE_EVIDENCE` | `HIGH` |
| 4 | `complex.validate` | `ConstraintValidation` | `RECIPE_RECOMMENDATION` | `complex.recipe_evidence` | `CONSTRAINT_VALIDATION` | `NORMAL` |
| 5 | `complex.response_plan` | `BuildResponsePlan` | `RECIPE_RECOMMENDATION` | `complex.validate` | `RESPONSE_PLAN` | `NORMAL` |

`SIMPLE` Route 不进入 Coordinator，由 `SimpleChatService` 直接处理。

## 3. 当前固定执行规则

当前 `RecipeCoordinator.coordinate()` 的基线规则如下：

1. 一次性构建当前 Route 的固定任务元组。
2. 按模板顺序将任务写入 Blackboard。
3. 按模板顺序串行遍历任务。
4. 依赖未成功时将任务标记为 `SKIPPED`。
5. 超出 `max_steps` 或 `max_budget` 时记录 `BUDGET_EXHAUSTED`，后续任务跳过。
6. 任务执行前由 `ExpertRegistry.resolve(capability)` 返回注册顺序中的第一个匹配 Expert。
7. Expert 返回的 Artifact 必须引用当前 Task ID。
8. 缺少任务声明的 Expected Artifact 时，任务转为 `FAILED` 并记录 `MISSING_ARTIFACT`。
9. Expert 异常、缺少 Expert、缺少 Artifact 或预算耗尽会使 Outcome 降级。

任务包 01 新增的 `OPEN`、`CLAIMED`、`ClaimDecision` 和候选排序尚未接入这条固定循环，因此不会改变基线业务输出。

## 4. 最终选择规则

固定 Coordinator 完成任务遍历后：

1. 查询 Blackboard 中全部 `RESPONSE_PLAN` Artifact。
2. 如果存在，以 `confidence` 最大者作为最终 Artifact。
3. Python `max()` 在置信度相同时保留最先出现的 Artifact。
4. 如果不存在 `RESPONSE_PLAN`：
   - 生成 `ArtifactKind.ERROR` 的结构化降级 Artifact；
   - Owner 为 `coordinator`；
   - Confidence 为 `0.0`；
   - 记录 `DEGRADED` 事件。
5. 调用 `select_final()` 写入 `final_artifact_id` 并追加 `FINAL_SELECTED` 事件。

任务包 01 只预定义后续审核/修订协议，不改变上述选择规则。审核通过后才能 `FINAL_ACCEPTED` 的行为属于后续任务包。

## 5. SSE 顺序基线

`POST /api/chat/stream` 当前在业务处理全部完成后开始输出 SSE，成功路径顺序固定为：

```text
meta
  -> status(stage="completed")
  -> source × 0..N
  -> token × 1..N
  -> done
```

各事件含义：

| 事件 | 数量 | 关键内容 |
|---|---:|---|
| `meta` | 1 | `sessionId`、`runId`、`route` |
| `status` | 1 | 当前固定值 `completed` |
| `source` | 0..N | Harness 返回的检索来源 |
| `token` | 1..N | 对已生成完整文本进行分块，不是模型实时 Token |
| `done` | 1 | `messageId` 与完整回答 |

异常路径只输出一个 `error` 事件，错误码根据异常类型为：

- `RESOURCE_NOT_FOUND`
- `ACCESS_DENIED`
- `CHAT_EXECUTION_FAILED`

任务包 01 不修改 SSE Schema、顺序或错误码。

## 6. 协作协议增量与兼容策略

### 6.1 新增任务状态及字段

- `TaskStatus.OPEN`
- `TaskStatus.CLAIMED`
- `AgentTask.claimed_by`
- `AgentTask.claim_confidence`
- `AgentTask.claim_reason`
- `AgentTask.revision_of`

原固定模板继续创建 `PENDING` 任务，并保持原 `PENDING -> RUNNING` 状态转换。

### 6.2 新增认领协议

- `ClaimDecision`
- `ExpertExecutor.decide(task, blackboard)`
- `BaseExpert` 的默认 capability-based `decide()`
- `ExpertCandidate`
- `ExpertRegistry.candidates()`
- `ExpertRegistry.claim_candidates()`
- `CollaborationBlackboard.claim_task()`
- `TASK_OPENED`
- `TASK_CLAIMED`

候选按以下稳定键排序：

```text
claim confidence 降序
  -> expert name 升序
```

`ExpertRegistry.resolve()` 保留给现有固定 Coordinator 过渡使用；任务包 01 不把新协调循环接入生产路径。

### 6.3 新增审核与修订协议

Artifact Kind：

- `RESPONSE_PROPOSAL`
- `REVIEW`
- `CRITIQUE`
- `REVISION`

关联字段：

- `AgentArtifact.review_of`
- `AgentArtifact.revision_of`
- `AgentTask.revision_of`

Event Type：

- `ARTIFACT_REVIEWED`
- `REVISION_REQUESTED`
- `FINAL_ACCEPTED`

这些字段和事件只作为后续质量审核闭环的协议基础，本包不执行审核或修订。

### 6.4 精确 Artifact 查询

新增：

- `artifact_for(task_id=..., kind=...)`
- `artifact_by_id(artifact_id)`

`artifact_for()` 要求 task id 与 kind 同时匹配；若同一精确依赖出现多个 Artifact，会明确抛出歧义错误，不再鼓励使用 `artifacts_for(kind)[-1]` 隐式依赖追加顺序。

## 7. 自动化测试基线

迁移前命令：

```powershell
D:\Anaconda\envs\rag\python.exe -m pytest -q `
  tests\unit\test_blackboard.py `
  tests\unit\test_coordinator.py `
  tests\unit\test_harness.py `
  tests\contract\test_sse_contract.py `
  tests\e2e\test_chat_api.py
```

迁移前结果：

```text
21 passed, 1 warning in 0.11s
```

Warning 为既有 Starlette TestClient/httpx 弃用提示，不由本任务包引入。

协议单元测试覆盖：

- Blackboard 不可变与深冻结；
- OPEN 任务认领；
- 重复认领拒绝；
- Claim 字段及事件可审计；
- task id + kind 精确 Artifact 查询；
- 候选 Expert 按置信度及稳定名称排序；
- 原固定 Coordinator 依赖、预算、失败降级和最终选择行为。

迁移后使用相同命令执行，结果：

```text
24 passed, 1 warning in 0.11s
```

新增 3 项测试后，原有 21 项基线测试继续通过；Warning 类型与迁移前一致。

同时执行：

```powershell
D:\Anaconda\envs\rag\python.exe -m ruff check `
  recipe_assistant\agents `
  tests\unit\test_blackboard.py `
  tests\unit\test_coordinator.py
```

结果：

```text
All checks passed!
```

## 8. 非目标

本包明确未实施：

- 动态派生缺失任务；
- 新协调循环中的竞价/认领调度；
- 并行执行；
- Guardrail 或 ResponseAgent；
- 审核失败后的修订循环；
- API/SSE 变更；
- 数据库迁移；
- Redis、Celery、消息队列或旧 ReactAgent。
