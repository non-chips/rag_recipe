# Collaborative Runtime 验证矩阵

## 协作协议（P05-T15）

| 能力 | 自动化证据 |
| --- | --- |
| 认领竞争、拒绝和稳定排序 | `tests/unit/test_coordinator.py`、`tests/unit/test_collaborative_coordinator.py` |
| 无候选与依赖失败 | `tests/unit/test_collaborative_coordinator.py::test_no_claim_and_budget_exhaustion_are_traced` |
| OPEN/CLAIMED/RUNNING/终态状态机 | `tests/unit/test_blackboard.py` |
| task id + kind 精确依赖 | `tests/unit/test_blackboard.py` 以及三类领域 Expert 回归 |
| 一次修订与修订耗尽 | `tests/unit/test_quality_review_loop.py` |
| 步骤、预算、轮次和认领上限 | `tests/unit/test_collaborative_coordinator.py` |
| 黑板不可变与事件递增序列 | `tests/unit/test_blackboard.py` |
| 串行单写者与重复运行稳定性 | `tests/unit/test_serial_runtime_performance.py` |

## 业务集成与 E2E（P05-T16）

| 场景 | 自动化证据 |
| --- | --- |
| 菜谱问答 | `tests/e2e/test_recipe_qa_flow.py` |
| 推荐与硬约束 | `tests/e2e/test_weather_recommendation_flow.py`、切换评测 recommendation case |
| 过敏原 | `tests/unit/test_quality_review_loop.py`、切换评测 `recommendation_allergen` |
| 天气与天气降级 | `tests/e2e/test_weather_recommendation_flow.py` |
| 营养报告 | `tests/integration/test_nutrition_report.py` |
| 无证据事实 | `tests/unit/test_quality_review_loop.py`、切换评测 `knowledge_ungrounded` |
| 工具降级 | `tests/unit/test_serial_runtime_performance.py`、`tests/integration/test_retrieval_degradation.py` |
| 审核与修订 | `tests/unit/test_quality_review_loop.py` |
| 点踩与 bad case | `tests/e2e/test_implicit_bad_case_flow.py`、`tests/e2e/test_bad_case_review_flow.py` |
| SSE 与持久化 | `tests/e2e/test_chat_api.py`、`tests/contract/test_sse_contract.py` |

## 发布验证结果

- Fixed/Collaborative 对比：全部 6 项切换门槛通过。
- Collaborative 关键离线用例：8/8，100%。
- 硬约束违反：0。
- 无证据具体事实率：0%。
- P95 延迟：不超过 fixed 的 1.25 倍。
- 协作路径无限循环：0。
- 预期 bad-case Trace 可追溯率：100%。
- Windows 15-flow smoke：15/15。
- Windows FastAPI/Streamlit 无容器启动冒烟：通过。

对比详情见 `coordination_cutover_report.json` 与
`coordination_cutover_report.md`。
