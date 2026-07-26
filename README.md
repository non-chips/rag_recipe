# 智能食谱助手

当前应用使用 FastAPI + 可替换 Streamlit Client。前端只通过 HTTP/SSE
访问后端，默认且唯一的业务运行时是 V2 多专家编排。

## Windows 11 启动

```powershell
$env:PROJECT_PYTHON = "D:\Anaconda\envs\rag\python.exe"  # 按本机路径调整
powershell.exe -ExecutionPolicy Bypass -File scripts\check_environment.ps1
powershell.exe -ExecutionPolicy Bypass -File scripts\start_api.ps1
```

另开一个 PowerShell：

```powershell
$env:PROJECT_PYTHON = "D:\Anaconda\envs\rag\python.exe"
powershell.exe -ExecutionPolicy Bypass -File scripts\start_streamlit.ps1
```

API 默认地址为 `http://127.0.0.1:8000`，Streamlit 默认地址为
`http://127.0.0.1:8501`。自动冒烟使用 `scripts/smoke_windows.ps1`。

## Runtime 配置

```dotenv
AGENT_RUNTIME_MODE=v2
AGENT_COORDINATION_MODE=collaborative
LEGACY_FALLBACK_ENABLED=false

# LLM：用于歧义上下文、低置信度路由和已验证 Artifact 的自然语言表达
CHAT_ENABLED=true
CHAT_MODEL=deepseek-v4-flash
CHAT_BASE_URL=https://api.deepseek.com
CHAT_API_KEY=your-api-key
CHAT_TIMEOUT_SECONDS=60
CHAT_MAX_RETRIES=2
CHAT_RESPONSE_MAX_CHARS=8000
CHAT_CONTEXT_MIN_CONFIDENCE=0.7
```

development、test 和 production 均只允许 V2。V2 执行失败时返回明确错误，
不会自动进入已下线链路。

模型由进程级 `ResourceContainer` 惰性创建并复用，不会在每次请求中重新
创建。`CHAT_ENABLED=false`、密钥缺失、超时、限流、网络错误、空回答或
过长回答都会回退到规则路由和确定性回答；领域检索、硬约束、营养计算、
食品安全审核及最终调度不会交给 LLM。模型文本只有通过 Guardrail 并产生
`FINAL_ACCEPTED` 后才会作为 SSE token 返回。

同一会话的最近 USER/ASSISTANT 消息会被限长、敏感令牌脱敏后形成显式
`CONVERSATION_CONTEXT` Artifact。明确的承接表达先走确定性规则；规则不能
判断时，由结构化 Context Agent 输出意图、历史菜名、独立检索词和置信度。
只有达到 `CHAT_CONTEXT_MIN_CONFIDENCE` 且菜名真实存在于最近对话时才会
回填路由与检索。助手展示的推荐菜名会按顺序保留在上下文 Artifact 中，
“第一道、第二个、最后一个”等表达优先走确定性位置映射。历史只用于指代
消解；制作时间、食材、厨具和忌口等临时约束仅从本轮用户输入提取，不能被
助手历史污染，也不能覆盖本轮检索证据、硬约束和食品安全审核。新会话不会
继承其他会话的短期上下文。

## 业务 Skill Runtime

协作式协调器会在领域 `RESPONSE_PLAN` 完成后运行确定性的
`context.skills` 任务，再生成 Response Proposal。当前业务 Skill 位于
`skills/*/SKILL.md`：

- `allergy_safe_recommendation`：过敏原与排除食材安全推荐；
- `ingredient_substitution`：食材替代建议；
- `source_aware_nutrition_report`：带数据来源边界的营养报告；
- `weather_aware_recommendation`：基于已验证天气 Artifact 的推荐。

业务运行时只读取上述目录结构，不读取仓库根目录的 `skills-lock.json`；
后者属于 Codex 工程能力依赖，不是食谱助手业务配置。Skill 不得覆盖用户
硬约束、候选校验结果或天气/营养等业务事实。

完整的数据流、启动失败策略、优先级、扩展步骤、迁移范围和 Trace 脱敏规则
见 `docs/skill_runtime/ARCHITECTURE.md`。

## 测试

```powershell
python -m pytest -q
python -m ruff check .
python -m compileall recipe_assistant rag graph frontend
```

Windows 完整冒烟：

```powershell
$env:PROJECT_PYTHON = "D:\Anaconda\envs\rag\python.exe"  # 按本机路径调整
powershell.exe -ExecutionPolicy Bypass -File scripts\smoke_windows.ps1
powershell.exe -ExecutionPolicy Bypass -File scripts\final_smoke_test.ps1
```

## 快速查看 Trace 与 Bad Case

```powershell
# 最近 5 条 Trace + Bad Case 摘要
powershell.exe -ExecutionPolicy Bypass -File scripts\inspect_diagnostics.ps1

# 最新一条完整 Trace
powershell.exe -ExecutionPolicy Bypass -File scripts\inspect_diagnostics.ps1 -View trace

# 指定 run_id
powershell.exe -ExecutionPolicy Bypass -File scripts\inspect_diagnostics.ps1 `
  -View trace -RunId "your-run-id"

# Bad Case 列表
powershell.exe -ExecutionPolicy Bypass -File scripts\inspect_diagnostics.ps1 `
  -View badcase -Limit 20

# 导出最新 Trace
powershell.exe -ExecutionPolicy Bypass -File scripts\inspect_diagnostics.ps1 `
  -View trace -Output reports\latest_trace.json
```

该脚本以只读方式访问 SQLite，不要求 FastAPI 正在运行。

### 负反馈与 Bad Case 审批闭环

用户通过 `POST /api/feedback` 提交 `DISLIKE` 后，`FeedbackService` 会读取
同一用户、会话和 run 对应的完整 Trace，并将 Trace、助手回答、反馈原因及
评论固化为一个 `PENDING_REVIEW` Bad Case 候选。同一 run 的重复反馈只更新
候选快照，不增加 occurrence；`LIKE` 不创建候选。

候选不会自动批准或进入回归数据集。开发者配置 `ADMIN_API_TOKEN` 后，使用
`GET /api/admin/bad-cases?status=PENDING_REVIEW` 查看待审候选，并通过
`POST /api/admin/bad-cases/{id}/approve`、`reject` 或 `merge` 完成显式审批。
所有审批操作都会写入追加式审计记录。

## 迁移与数据保护

- 当前架构：`docs/current_architecture.md`
- V2 最终架构：`docs/migration/final_architecture.md`
- 下线最终报告：`docs/migration/legacy_decommission_report.md`
- 调用者审计：`docs/migration/legacy_callers_report.md`
- 已删除文件：`docs/migration/removed_legacy_files.md`
- 数据备份：`docs/migration/data_backup_plan.md`
- 回滚说明：`docs/migration/rollback.md`

最终验证：

```powershell
$env:PROJECT_PYTHON = "D:\Anaconda\envs\rag\python.exe"
powershell.exe -ExecutionPolicy Bypass -File scripts\final_smoke_test.ps1
python scripts\run_evaluation.py --output reports\final_evaluation.json
```

下线基线由 `pre-legacy-decommission` 标签和
`archive/legacy-react-agent` 分支保护。SQLite、Chroma、BM25、Neo4j、
菜谱源文件和营养目录不属于旧业务代码删除范围。
