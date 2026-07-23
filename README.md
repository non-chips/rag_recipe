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
LEGACY_FALLBACK_ENABLED=false
```

development、test 和 production 均只允许 V2。V2 执行失败时返回明确错误，
不会自动进入已下线链路。

## 测试

```powershell
python -m pytest -q
python -m ruff check .
python -m compileall recipe_assistant frontend
```

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
