# Task 19 最终迁移与发布门禁报告

日期：2026-07-22

## 评测结果

执行 `D:\Anaconda\envs\rag\python.exe scripts\run_evaluation.py`，本机离线确定性基线
共 41 个用例，41 通过、0 失败：业务路由 33、检索 3、推荐 1、营养 2、反馈 1、
Bad Case 1。首次 Task 19 基线实测汇总如下：

| 指标 | 结果 |
| --- | ---: |
| 全部用例 P50 | 0.011 ms |
| 全部用例 P95 | 0.714 ms |
| 模型调用 | 0 |
| 检索后端/证据调用 | 9 |
| 显式降级次数 | 2 |

两次降级分别是检索后端故障后的向量降级，以及营养覆盖率 0.5 时拒绝给出精确结论。
这些数据是当前机器上的本地 Service 基线；未调用生产 LLM、Neo4j、Chroma 或外部 API，
不能外推为线上吞吐、准确率或响应时间提升。每次运行可通过 `--output <path>` 保存完整
逐用例 JSON，困难用例未从数据集中删除。

## Windows 11 无容器验证

在 Windows build 26200、Python 3.11.15 环境执行：

```powershell
$env:PROJECT_PYTHON = "D:\Anaconda\envs\rag\python.exe"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\smoke_windows.ps1
```

环境检查通过；FastAPI `/actuator/health` 返回 `UP`；Streamlit
`/_stcore/health` 返回 200。脚本使用隐藏后台进程，结束时按已记录 PID 清理，不依赖 Docker。
Python 的 `platform.platform()` 在该系统上返回兼容标签 `Windows-10-10.0.26200-SP0`；
Windows 版本应结合 build 号判断。

手工启动顺序：

```powershell
$env:PROJECT_PYTHON = "D:\Anaconda\envs\rag\python.exe"
powershell.exe -ExecutionPolicy Bypass -File scripts\start_api.ps1
# 新开 PowerShell
$env:PROJECT_PYTHON = "D:\Anaconda\envs\rag\python.exe"
powershell.exe -ExecutionPolicy Bypass -File scripts\start_streamlit.ps1
```

默认地址分别为 `http://127.0.0.1:8000` 和 `http://127.0.0.1:8501`。

## 旧入口调用分析与迁移状态

| 旧组件 | 当前调用方 | 决策 |
| --- | --- | --- |
| `app.py` | 用户可能仍以旧 README 命令启动 | 标记弃用，暂不删除 |
| `agent/react_agent.py` | `app.py`、`LazyLegacyExecutor`、基线测试 | 兼容回退仍存活，暂不删除 |
| `agent/tools/agent_tools.py` | `ReactAgent` | 随旧 Agent 保留 |
| `rag/hybrid_rag_service.py` | 旧工具和基线测试 | 保留至旧 Agent 下线 |
| `graph/` | 新 `RetrievalService` 的可选 Graph 后端及旧 Hybrid | 仍有运行调用，不删除 |
| 旧 BM25 接口 | 新适配器和旧 Hybrid | 已能脱离 Neo4j 独立运行，保留兼容 |

本轮没有批量删除文件，因为调用分析没有找到可确认“无调用且无兼容意义”的旧业务文件。
后续删除条件是：默认聊天不再回退 `LazyLegacyExecutor`、基线测试迁到新入口、用户完成
至少一个弃用周期，并再次用 `rg` 与导入测试确认无调用。

## 发布门禁与未决风险

- 自动回归与离线业务评测可以作为当前代码质量基线。
- `recipe_assistant/api/feedback.py` 与 `recipe_assistant/api/admin_bad_cases.py` 尚未由默认
  `api_router` 注册。服务及独立集成测试通过不等于默认 Runtime 可访问；在修复前，包含
  前端反馈/管理功能的完整发布门禁不通过。
- MCP SDK 是可选依赖；`MCP_ENABLED=false` 的默认无资源模式可运行，启用 MCP 前需安装 SDK。
- 营养目录仍需可信数据源导入；系统不会自行生成可当作事实的营养数值。
