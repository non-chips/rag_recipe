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
| 09 | IN_PROGRESS | 未提交 | 指定测试：9 passed；Task 01 基线：6 passed；限定 Ruff：通过 | 交付完成，等待人工验收；仅使用 Fake Expert 验证，未实现三个领域专家 |
| 10 | TODO |  |  |  |
| 11 | TODO |  |  |  |
| 12 | TODO |  |  |  |
| 13 | TODO |  |  |  |
| 14 | TODO |  |  |  |
| 15 | TODO |  |  |  |
| 16 | TODO |  |  |  |
| 17 | TODO |  |  |  |
| 18 | TODO |  |  |  |
| 19 | TODO |  |  |  |

状态只允许：`TODO`、`IN_PROGRESS`、`BLOCKED`、`DONE`。

## 当前阻塞

- 无

## 关键架构决策

- 前端只通过 FastAPI API/SSE 访问后端。
- Windows 11 本地运行，不依赖 Docker。
- 三专家：知识、推荐、营养。
- Bad Case 必须由开发者审批。
