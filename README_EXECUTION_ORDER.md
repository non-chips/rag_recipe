# Codex 分步执行计划

本目录将长篇架构规范拆成 **20 个可独立交付的任务**。每次只把以下内容交给 Codex：

1. `README_EXECUTION_ORDER.md`
2. 当前任务文件，例如 `task_04.md`
3. 当前任务“必须阅读”中列出的源码文件
4. `CODEX_PROGRESS.md`

不要一次性把所有任务文件都交给 Codex。

## 使用方法

```text
完成 task_00
→ 人工检查完成报告和 Git diff
→ 运行验收命令
→ 提交 Git
→ 更新 CODEX_PROGRESS.md
→ 再进入 task_01
```

任何任务验收失败时，停留在当前任务修复，不进入下一任务。

## 执行顺序

| 编号 | 任务 | 文件 |
| --- | --- | --- |
| 00 | 仓库现状盘点与冻结基线 | `task_00.md` |
| 01 | 测试与工程基线 | `task_01.md` |
| 02 | 统一配置与资源容器 | `task_02.md` |
| 03 | 检索数据契约与元数据统一 | `task_03.md` |
| 04 | RetrievalService 解耦与旧接口适配 | `task_04.md` |
| 05 | 本地 Tool Registry 与权限治理 | `task_05.md` |
| 06 | 业务路由与简单聊天快速路径 | `task_06.md` |
| 07 | SQLite 数据模型与 Repository | `task_07.md` |
| 08 | Harness、ChatService 与统一运行结果 | `task_08.md` |
| 09 | 事件、Artifact、黑板与 Coordinator | `task_09.md` |
| 10 | 菜谱知识专家 | `task_10.md` |
| 11 | 菜谱推荐专家与硬约束校验 | `task_11.md` |
| 12 | 营养数据、营养服务与营养规划专家 | `task_12.md` |
| 13 | FastAPI、SSE 与 Streamlit 客户端解耦 | `task_13.md` |
| 14 | 显式反馈与回答/菜谱偏好分离 | `task_14.md` |
| 15 | 隐式反馈信号与 Bad Case 候选评分 | `task_15.md` |
| 16 | 可能根因分析与开发者审批 | `task_16.md` |
| 17 | Skills 行为约束 | `task_17.md` |
| 18 | 可选 MCP 高层工具暴露 | `task_18.md` |
| 19 | 完整评测、Windows 运行与旧代码清理 | `task_19.md` |

## 阶段分组

- **基础保护（00—04）**：盘点、测试、配置容器、检索契约、RetrievalService。
- **架构骨架（05—09）**：Tool 权限、业务路由、持久化、Harness、Coordinator。
- **领域能力（10—12）**：知识、推荐、营养三个专家。
- **低耦合应用（13）**：FastAPI/SSE 与 Streamlit API Client。
- **反馈闭环（14—16）**：显式反馈、隐式信号、Bad Case 审批与回归。
- **扩展与收尾（17—19）**：Skills、可选 MCP、评测和清理。

## 进入下一任务的统一门槛

- 当前任务规定的测试通过；
- `git diff` 仅包含当前任务允许范围；
- 旧主链路仍可运行，或任务明确说明了兼容替代；
- 没有新增硬编码密钥、本地绝对路径和容器依赖；
- `CODEX_PROGRESS.md` 已记录完成状态、测试结果、风险与提交编号；
- 人工确认后再开始下一任务。

## 长规范的使用方式

`RAG_RECIPE_V2_PROJECT_STRUCTURE_WITH_FEEDBACK.md` 是架构参考，不是单次执行指令。

当长规范与当前任务范围发生冲突时：

1. 当前任务的“禁止事项”和“允许修改范围”优先；
2. 不确定时停止编码，在完成报告中提出问题；
3. 不得为了实现长规范中的未来功能而越过当前任务。
