# 本地数据与索引备份方案

## 目标与边界

Task 20 只做可恢复快照，不修改数据库 Schema、不重建索引、不删除源数据。备份脚本为 Windows PowerShell，默认输出到 Git 已忽略的 `storage/decommission_backups/<UTC 时间>/`。

## 运行前条件

1. 停止 FastAPI、旧/新 Streamlit、导入脚本以及可能写入 SQLite/Chroma 的 Python 进程。
2. 记录当前提交：`git rev-parse HEAD`。Task 20 基线应为 `3af76831338fb22bec66fbeaf30b3d6e0ec4e4c1`。
3. 若 Neo4j 已启用，先按下文生成一致性 dump；仅复制重建脚本不等于 Neo4j 数据备份。
4. 确认目标磁盘有足够空间，且备份目录不位于 `storage/chroma_db` 内。

## 自动备份

基础备份：

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts\backup_local_data.ps1
```

包含本地 `.env`（包含密钥，仅在受控磁盘使用）：

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts\backup_local_data.ps1 `
  -IncludeEnvironmentFile
```

已有 Neo4j dump 时一并封存：

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts\backup_local_data.ps1 `
  -Neo4jDumpPath D:\backups\neo4j.dump
```

脚本复制：

- `storage/recipe_assistant.db` 及存在时的 WAL/SHM；
- `storage/chroma_db/`；
- `storage/parent_documents.json`、`recipe_md5.text`、`child_chunk_counts.csv`；
- `config/`、`.env.example`，以及显式允许时的 `.env`；
- `graph/` 重建代码、`data/nutrition/`；
- 可选 Neo4j dump；
- `manifest.json`（基线提交、文件长度、SHA-256、缺失项和 Neo4j 状态）。

## Neo4j 一致性备份

Neo4j 是外部服务，不能通过复制仓库目录备份。应使用与已安装 Neo4j 版本匹配的管理工具，并在 Neo4j 停止写入后执行：

```powershell
neo4j-admin database dump neo4j --to-path=D:\backups\neo4j
```

不同 Neo4j 版本的 CLI 参数可能不同，执行前必须运行 `neo4j-admin database dump --help`。如果环境没有 Neo4j 或 `NEO4J_ENABLED=false`，在清单中记录 `not-provided`；此时恢复路径是用 Git 固定的 `data/recipes/`、`graph/` 和 `config/graph.yml` 重新构建：

```powershell
python -m graph.build_graph_store
```

重建只能恢复由菜谱源文档生成的图，不保证恢复外部数据库中未落入源码的人工修改，因此不能冒充 dump。

## 校验与恢复演练

查看备份清单：

```powershell
Get-Content -Raw storage\decommission_backups\<timestamp>\manifest.json
```

重新计算任一文件哈希：

```powershell
Get-FileHash storage\decommission_backups\<timestamp>\data\sqlite\recipe_assistant.db -Algorithm SHA256
```

恢复前先停止所有运行进程，并把当前文件移动到隔离目录。SQLite 必须同时处理 `db`、`-wal`、`-shm`；Chroma 必须整目录恢复，不能混用两个快照中的 `chroma.sqlite3` 和向量分片。恢复后执行：

```powershell
python -m pytest -q
powershell.exe -ExecutionPolicy Bypass -File scripts\check_environment.ps1
```

## 保留策略

- 至少保留 Task 20 基线快照、Task 22 切换前快照、Task 24 每批删除前快照。
- 每份备份至少复制到另一个物理磁盘或受控备份位置；仓库内忽略目录不是灾难恢复副本。
- 含 `.env` 或 Neo4j dump 的备份按敏感数据处理，不提交 Git，不发送到公共网盘。
- 在 Task 25 完成前不得清理 `pre-legacy-decommission` 备份。
