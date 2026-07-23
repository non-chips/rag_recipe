# 旧业务下线最终报告

## 关闭结论

Task20—Task25 已完成。旧业务运行时代码已分批删除，FastAPI、Streamlit
Client 和 V2 测试不再加载旧模块；完整测试、静态检查、编译、离线评测、
环境检查及 15 类 Smoke 均通过。旧业务代码迁移状态正式关闭。

## 阶段结果

| 阶段 | 结果 |
| --- | --- |
| Task20 冻结与备份 | Git 标签/归档分支建立；44 个备份文件校验无失败 |
| Task21 新旧对照 | 20/20；P0 7/7；P1 12/12；API/数据一致性 100% |
| Task22 V2 默认切换 | 120/120 人工回放；旧链路主响应 0 |
| Task23 零调用隔离 | 正常 Runtime 禁止引用 0；启动不加载旧模块 |
| Task24 分批删除 | 5 批及模型工厂补充批次；每批 158 passed |
| Task25 最终验证 | 158 passed；离线评测 41/41；Smoke 15/15 |

## 最终指标

- 全量 pytest：158 passed，2 个第三方弃用警告。
- 离线评测：41/41，P50 0.011 ms，P95 0.355 ms。
- 15 类 Smoke：15/15，约 24.6 秒（每项独立 pytest 进程）。
- 静态扫描：正常 Runtime 禁止旧引用为 0。
- Ruff、compileall、Windows 环境检查：通过。

以上延迟是本机确定性离线组件基线，不代表 DeepSeek、AMap、Chroma 或
Neo4j 的生产容量。

## 数据验证结果

Task25 未执行数据删除或数据迁移。

| 数据 | 结果 |
| --- | --- |
| SQLite | 必需表全部存在；当前会话 1、消息 2、Trace 1 |
| 反馈/Bad Case | 表与 API/工作流 Smoke 通过；当前持久库行数均为 0 |
| 饮食记录 | 当前持久库 0 行；事件类型约束有效 |
| QUERY/CONSUME | API 明确拒绝把 QUERY 作为确认用餐；离线评测和 Smoke 通过 |
| Chroma | 17 个文件，约 29.6 MB；只读验证通过 |
| 营养目录 | JSON 结构合法，但当前 0 条，状态为 `empty_requires_import` |
| Neo4j | 默认关闭；Adapter 与重建源存在；未做实时连通性检查 |

Neo4j 没有外部 database dump，因此不能宣称外部图数据库数据已完成恢复演练。

## 删除与保留

删除清单和每批提交见 `removed_legacy_files.md`。继续保留：

- Chroma VectorStore、本地 embedding 模型和父子块索引；
- BM25、文档源、RRF、RetrievalRouter、metadata normalizer；
- Neo4j Adapter、Parser、Builder 和重建入口；
- WeatherService、营养/约束/反馈/Bad Case/Trace 服务；
- SQLite、Chroma、Neo4j、菜谱源文档和营养目录。

## 已知差异与风险

1. V2 不提供在线 legacy/shadow/fallback；故障会显式失败或按 V2 服务降级。
2. 营养目录为空，真实精确营养指标需导入可信数据后重新评测。
3. Neo4j 默认关闭且无 dump，当前只验证代码与可重建性。
4. 最终评测不调用生产 LLM 或远程天气服务。
5. Starlette TestClient 与 jieba 依赖产生两个第三方弃用警告，不影响当前验收。

## 回滚

- Task25 报告与脚本可反向提交，不涉及数据恢复。
- Task24 删除提交必须按 Git 逆序逐批 `git revert`。
- 完整旧链路仍可从 `archive/legacy-react-agent` 或
  `pre-legacy-decommission` 在独立 worktree 中查看。
- 代码回滚与数据恢复必须分开审批；不得覆盖当前 SQLite/Chroma。
