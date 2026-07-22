# Codex 执行进度

> 每完成一个任务更新一行；未通过人工验收不得标记 DONE。

| 编号 | 状态 | Git 提交 | 测试结果 | 风险/备注 |
| --- | --- | --- | --- | --- |
| 00 | DONE | 未提交 | `compileall` 通过；纯模块与 `ReactAgent` 导入通过 | 用户已明确要求进入 Task 01；普通 Agent 导入后的资源生命周期风险保留 |
| 01 | DONE | 未提交 | `pytest tests/baseline -q`：6 passed；`ruff check .`：通过 | 用户已明确要求进入 Task 02；外部服务测试均使用离线 Fake |
| 02 | DONE | 未提交 | 指定单元测试：8 passed；限定 Ruff：通过；Task 01 基线：6 passed | 用户已明确要求进入 Task 03；新容器尚未接入旧运行链路，符合本任务停止条件 |
| 03 | DONE | `d8c8ef3` | 指定单元测试：9 passed | 用户已明确要求进入 Task 04；数据契约已提交 |
| 04 | DONE | `d45da70` | 指定测试：8 passed；Task 01 基线：6 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 05；RetrievalService 解耦已提交 |
| 05 | DONE | `3e7fe82` | 指定测试：9 passed；Task 01 基线：6 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 06；Tool Registry 与权限治理已提交 |
| 06 | DONE | `e4548f3` | 指定测试：7 passed（33 条样例）；Task 01 基线：6 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 07；业务路由与 SIMPLE 快速路径已提交 |
| 07 | DONE | `d8481b5` | 指定测试：6 passed；Alembic upgrade/check 通过；Task 01 基线：6 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 08；SQLite 数据层与迁移已提交 |
| 08 | DONE | `97dc1c6` | 指定测试：6 passed；Task 01 基线：6 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 09；统一生命周期已提交 |
| 09 | DONE | `c582a53` | 指定测试：9 passed；Task 01 基线：6 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 10；协作协议与确定性编排已提交 |
| 10 | DONE | `b3450ca` | 指定测试：5 passed；相邻层回归：26 passed；Task 01 基线：6 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 11；菜谱知识专家已提交 |
| 11 | DONE | `287e837` | 指定测试：9 passed；相邻层回归：27 passed；Task 01 基线：6 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 12；推荐专家与硬约束服务已提交 |
| 12 | DONE | `6f8dc79` | 指定测试：8 passed；相邻层回归：29 passed；Task 01 基线：6 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 13；营养服务、专家与 JSON 报告已提交 |
| 13 | DONE | `af4a760` | 指定测试：12 passed；PowerShell 环境检查：通过；相邻层回归：28 passed；Task 01 基线：6 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 14；FastAPI + SSE 与可替换 Streamlit 前端已提交 |
| 14 | BLOCKED | 未提交 | 指定测试：5 passed；Alembic upgrade/check：通过；限定 Ruff：通过 | 反馈实现已完成白名单内部分；默认 API 仍需在静态主路由中注册，但 `recipe_assistant/api/router.py` 不在 Task 14 允许修改范围内 |
| 15 | DONE | `02cf539` | 指定测试：8 passed；Alembic upgrade/check：通过；相邻反馈/约束/Trace 回归：10 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 16；规则型弱信号、候选评分与去重已提交 |
| 16 | DONE | `d99ad5c` | 指定测试：10 passed；完整回归：125 passed；Alembic upgrade/check：通过；限定 Ruff：通过 | 用户已明确要求进入 Task 17；根因建议、审批审计、状态机和回归草稿已提交；默认管理路由注册风险保留 |
| 17 | DONE | `591cf44` | 指定测试：10 passed；完整回归：135 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 18；Skill Registry、基础行为 Skill 和编写规范已提交 |
| 18 | IN_PROGRESS | 未提交 | 指定测试：6 passed；限定 Ruff：通过 | 四项高层 MCP Tool、服务语义一致性、可信用户注入和关闭时零资源初始化已完成，等待人工验收 |
| 19 | TODO |  |  |  |

状态只允许：`TODO`、`IN_PROGRESS`、`BLOCKED`、`DONE`。

## 当前阻塞

- Task 14 的反馈路由已定义，但现有 Task 13 主路由采用静态注册；需获准修改白名单外的 `recipe_assistant/api/router.py` 后才能让默认 API 与前端访问该端点。
- Task 16 的管理路由同样已定义并通过独立集成测试，但需获准修改 `recipe_assistant/api/router.py` 后才能接入默认 API Runtime。

## 关键架构决策

- 前端只通过 FastAPI API/SSE 访问后端。
- Windows 11 本地运行，不依赖 Docker。
- 三专家：知识、推荐、营养。
- Bad Case 必须由开发者审批。
