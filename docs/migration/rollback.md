# 旧业务下线回滚手册

## 冻结点

Task 20 将 Task 19 后的提交 `3af76831338fb22bec66fbeaf30b3d6e0ec4e4c1` 定义为旧业务下线前基线：

```powershell
git tag pre-legacy-decommission 3af76831338fb22bec66fbeaf30b3d6e0ec4e4c1
git branch archive/legacy-react-agent 3af76831338fb22bec66fbeaf30b3d6e0ec4e4c1
```

验证引用：

```powershell
git show --no-patch --decorate pre-legacy-decommission
git rev-parse archive/legacy-react-agent
```

标签和归档分支均为本地引用；若存在受控远端，应由维护者审核后显式推送，Task 20 不自动修改远端。

## 回滚原则

- 优先新建恢复分支或反向提交，不在有用户修改的工作区执行 `git reset --hard`。
- 代码回滚和数据恢复分开审批、分开执行。
- 恢复前先停服务并备份故障现场，避免覆盖唯一证据。
- 只回滚失败的小批次；不得因单批下线失败丢弃 Task 00—19 的全部 V2 工作。

## 代码回滚

仅检查基线：

```powershell
git switch --detach pre-legacy-decommission
```

从基线创建可写恢复分支：

```powershell
git switch -c recovery/pre-legacy-decommission pre-legacy-decommission
```

已提交的小批次下线回滚：

```powershell
git revert <failed-decommission-commit>
```

若需要查看完整旧链路而不改变当前分支：

```powershell
git worktree add ..\ragdemo-legacy archive/legacy-react-agent
```

## 数据回滚

1. 停止 FastAPI、Streamlit、摄取脚本和 Neo4j 写入。
2. 校验备份 `manifest.json` 中的 SHA-256。
3. 将现有 `storage/recipe_assistant.db*` 和 `storage/chroma_db/` 移到带时间戳的故障隔离目录。
4. 从同一份 Task 20 快照恢复 SQLite、WAL/SHM、完整 Chroma 目录和父文档文件。
5. Neo4j 使用匹配版本的 `neo4j-admin database load` 从 dump 恢复；没有 dump 时只能从固定版本源文档重建。
6. 运行环境检查、全量测试和只读数据计数核对，再恢复流量。

禁止把旧 Chroma SQLite 元数据与新向量分片拼接，也禁止在不清楚数据时间点时覆盖当前业务 SQLite。

## 不可逆操作与补偿

| 不可逆或高风险操作 | 执行前门槛 | 回滚/补偿 |
| --- | --- | --- |
| 删除旧入口、Agent、Tool、路由 | Task 21 等价通过、Task 23 零调用、独立提交 | `git revert` 对应删除提交；必要时从归档分支恢复单文件 |
| 删除/修改 SQLite 表或列 | 不属于 Task 20；必须独立迁移和备份 | 使用 Alembic 明确降级或从一致性 SQLite 快照恢复 |
| 清空/重建 Chroma | 完整目录备份和可复现摄取版本 | 整目录恢复；否则从固定源文档重建并重新评测 |
| 删除父文档/摄取辅助文件 | 与 Chroma 同一时间点备份 | 从同一快照恢复，禁止跨快照混用 |
| Neo4j `DROP`、清库或重建 | 有可验证 dump 或书面接受仅可重建 | `neo4j-admin database load`；无 dump 时从源文档重建但人工增量会丢失 |
| 覆盖 `.env`/密钥配置 | 已加密或受控备份 | 恢复配置并轮换已暴露密钥 |
| 删除 Git 标签/归档分支 | 下线关闭审计完成并获得人工批准 | 从已推送远端/另一克隆恢复引用；若均不存在则无法保证完整恢复 |

## 立即回滚触发条件

- 过敏原、排除食材等硬约束失效；
- 会话、反馈、饮食记录或用户资料丢失/串号；
- 默认 API 无法启动、主要 Route 大面积错误或 SSE 大面积中断；
- 检索索引不可读且无法通过已批准降级继续服务；
- 数据迁移无法验证或恢复演练失败。

## Task 20 自身回滚

Task 20 只增加文档、备份脚本、Git 引用和忽略目录中的备份。回滚时可反向提交 Task 20 的跟踪文件；备份应保留到 Task 25 关闭迁移后再由人工清理。不要删除 `pre-legacy-decommission` 标签或 `archive/legacy-react-agent` 分支。
