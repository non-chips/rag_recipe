# Fixed 与 Collaborative 协调模式切换评测

## 指标

| 指标 | fixed | collaborative |
| --- | ---: | ---: |
| 用例通过率 | 62.50% | 100.00% |
| 硬约束违反数 | 1 | 0 |
| 无证据事实率 | 12.50% | 0.00% |
| P50 延迟(ms) | 52.999 | 65.204 |
| P95 延迟(ms) | 63.636 | 76.033 |
| Tool/领域执行代理次数 | 40 | 44 |
| 降级率 | 12.50% | 37.50% |
| Bad case 命中率 | 0.00% | 25.00% |

## 切换门槛

| 门槛 | 结果 |
| --- | --- |
| critical_cases_100_percent | PASS |
| hard_constraint_violations_zero | PASS |
| ungrounded_fact_rate_not_worse | PASS |
| p95_latency_within_1_25x | PASS |
| infinite_loops_zero | PASS |
| bad_case_traceability_100_percent | PASS |

**切换结论：APPROVED**

Fixed 删除结论：**DEFERRED**。当前保留显式回退，等待提交备份和生产零调用观察证据。

复现命令：

```powershell
D:\Anaconda\envs\rag\python.exe scripts\compare_coordination_modes.py
```
