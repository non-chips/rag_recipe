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
| 14 | DONE | `task21 remediation commit` | 原指定测试：5 passed；Task 21 路由/契约修复验证通过 | 反馈路由已注册默认 API，原白名单阻塞在 Task 21 修复中解除 |
| 15 | DONE | `02cf539` | 指定测试：8 passed；Alembic upgrade/check：通过；相邻反馈/约束/Trace 回归：10 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 16；规则型弱信号、候选评分与去重已提交 |
| 16 | DONE | `d99ad5c` | 指定测试：10 passed；完整回归：125 passed；Alembic upgrade/check：通过；限定 Ruff：通过 | 用户已明确要求进入 Task 17；根因建议、审批审计、状态机和回归草稿已提交；默认管理路由注册风险保留 |
| 17 | DONE | `591cf44` | 指定测试：10 passed；完整回归：135 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 18；Skill Registry、基础行为 Skill 和编写规范已提交 |
| 18 | DONE | `fde9f1d` | 指定测试：6 passed；限定 Ruff：通过 | 用户已明确要求进入 Task 19；四项高层 MCP Tool、服务语义一致性、可信用户注入和关闭时零资源初始化已提交 |
| 19 | DONE | 未提交 | 离线评测：41/41；完整回归：141 passed；Ruff：通过；Windows API/Streamlit 冒烟：通过 | 旧入口仍有调用，未删除；默认反馈/管理路由未注册的发布风险保留并写入最终迁移报告 |
| 20 | DONE | `pre-legacy-decommission` / `archive/legacy-react-agent` → `3af7683` | 数据备份 44 文件、SHA-256 0 失败；完整回归：141 passed；Ruff：通过；Windows 环境检查：通过 | 仅完成冻结、盘点和备份；默认入口未切换、旧代码未删除；Neo4j dump 未提供；Task 14 状态仍为 BLOCKED |
| 21 | DONE | `task21 evidence + remediation commits` | 对照评测：20/20；P0：7/7；P1：12/12；API/数据一致性：100%；针对性测试：9 passed | 反馈与 Bad Case 路由已注册；V2 Runtime 可直接执行；默认 Runtime 保持旧实现并留给 Task 22 切换 |
| 22 | DONE | `3550960` | 默认切换专项：10 passed；完整回归：154 passed；Ruff：通过；Windows 环境检查：通过；观测回放：120/120 | 默认 Runtime 已切换 V2；Task 23 将在线回滚入口进一步隔离；未删除旧代码 |
| 23 | DONE | `683b1ff` | 零调用专项：3 passed；完整回归：158 passed；静态扫描：正常 Runtime 禁止引用 0；Ruff/compileall：通过 | 容器不再注册旧适配器；development/test/production 均只允许 V2；旧文件与历史回归证据仍保留 |
| 24 | DONE | `1bc12fb`、`7bc35fd`、`fabd86b`、`cb18be4`、`1ec3a7a`、`582de66` | 每批完整回归：158 passed；每批 Ruff/compileall：通过；最终环境检查：通过 | 旧入口、路由、Tool、Agent、Adapter、回答 Facade 和混合模型工厂已分批删除；底层检索、图、天气、metadata 与全部数据保留 |

状态只允许：`TODO`、`IN_PROGRESS`、`BLOCKED`、`DONE`。

## 当前阻塞

- 无阻止进入 Task 25 的代码门禁失败；Task 24 分批删除验收已完成。
- Task 20 已备份 Neo4j 可重建材料，但没有外部 Neo4j 数据库 dump；启用 Neo4j 的环境在任何清库或重建前必须补充一致性 dump。
- 默认 FastAPI 与 V2 测试只使用新链路；Task 24 删除清单与回滚点已形成审计报告。

## 关键架构决策

- 前端只通过 FastAPI API/SSE 访问后端。
- Windows 11 本地运行，不依赖 Docker。
- 三专家：知识、推荐、营养。
- Bad Case 必须由开发者审批。
