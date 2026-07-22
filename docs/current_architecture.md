# 当前架构基线

## 1. 基线范围

本文记录 Task 00 执行时工作区中的实际实现，用于后续迁移对照，不代表目标架构，也不声明性能、准确率或召回率提升。

- 应用入口：`app.py`
- Agent：`agent/react_agent.py`
- Tool 与路由：`agent/tools/`、`agent/routing/`
- 检索：`rag/`
- 图谱：`graph/`
- 模型与配置：`model/factory.py`、`config/`、`utils/config_handler.py`
- 数据：`data/recipes/`，当前扫描到 323 个 Markdown 菜谱文件
- 本地检索产物：`storage/chroma_db/`、`storage/parent_documents.json`、`storage/recipe_md5.text`

当前工作树在 Task 00 开始前已经存在未提交的运行时代码修改。本基线描述的是当前工作树，而不是仅描述 `HEAD` 提交；Task 00 不修改、撤销或整理这些既有修改。

## 2. 当前调用链

```text
Streamlit app.py
  ├─ st.session_state["agent"] = ReactAgent()
  ├─ st.session_state["thread_id"]
  └─ ReactAgent.execute_stream(query, thread_id)
       └─ LangChain create_agent + InMemorySaver
            ├─ middleware.log_before_model
            └─ 模型自主选择 Tool
                 ├─ get_user_location
                 │    ├─ 公网 IP 服务
                 │    └─ 高德 /v3/ip
                 ├─ get_weather
                 │    ├─ 高德 /v3/geocode/geo
                 │    └─ 高德 /v3/weather/weatherInfo
                 └─ smart_recipe_query
                      └─ RecipeQueryRouter.route(mode="auto")
                           ├─ LLM 路由
                           └─ 异常时规则路由
                                ├─ vector_search
                                │    └─ RagSummarizeService
                                │         ├─ Chroma 子块检索
                                │         ├─ parent_id 回取父块 JSON
                                │         └─ DeepSeek 生成答案
                                ├─ graph_search
                                │    └─ GraphRecipeRetriever
                                │         └─ Neo4j Cypher 查询
                                └─ hybrid_search
                                     └─ HybridRagService
                                          ├─ GraphRecipeRetriever / Neo4j
                                          ├─ Chroma 父子块检索
                                          ├─ BM25RecipeRetriever
                                          │    └─ 从 Neo4j 重构完整菜谱文档并建索引
                                          ├─ RRF 三路融合
                                          └─ DeepSeek 生成答案
```

### 2.1 会话与流式输出

- Streamlit 为每个浏览器会话保存一个 `ReactAgent` 实例和 UUID `thread_id`。
- Agent 使用 `InMemorySaver` 保存同一 `thread_id` 的短期状态。
- 页面展示历史另存于 `st.session_state["messages"]`，不是持久化后端。
- 应用重启、进程退出或浏览器会话丢失后，当前记忆不可恢复。
- 当前前端直接导入并实例化 Agent；这是必须保留的旧链路，也是后续通过 HTTP API/SSE 适配迁移的边界。

### 2.2 菜谱路由

- 主 Agent 先通过模型自主决定是否调用菜谱 Tool。
- `smart_recipe_query` 内部再执行一次 `RecipeQueryRouter`。
- `mode="auto"` 先调用聊天模型生成结构化路由；失败时使用规则计划。
- 路由输出包含检索方法、复杂度、关系密度、食材包含/排除、工具、分类和天气需求等字段。
- 当前 Hybrid 调用只把原始 query 传给 `HybridRagService`，没有完整传递路由产生的全部结构化字段。

### 2.3 普通 RAG

```text
query
  → Chroma similarity_search(child_k)
  → 依据 parent_id 从 parent_documents.json 回取父块
  → Top-K 父块拼接为上下文
  → Prompt + DeepSeek
  → 字符串答案
```

索引构建时扫描 Markdown，按父块/子块切分，将子块写入 Chroma，并用 schema version + 文件 MD5 跳过已处理文件。

### 2.4 Graph 检索

图谱包含以下节点与关系：

| 节点 | 关键标识 |
| --- | --- |
| `Recipe` | `nodeId` |
| `Ingredient` | `name` |
| `RecipeCategory` | `name` |
| `CookingStep` | `nodeId` |
| `CookingTool` | `name` |

| 关系 | 含义 |
| --- | --- |
| `REQUIRES` | 菜谱所需食材及用量 |
| `USES_TOOL` | 菜谱所需工具 |
| `CONTAINS_STEP` | 菜谱步骤与顺序 |
| `BELONGS_TO_CATEGORY` | 菜谱分类 |

`recipe_id` 由菜谱文件相对于数据根目录的路径做 SHA-256 截断生成。图谱查询当前直接返回 `dict` 列表或转换成 LangChain `Document`。

### 2.5 Hybrid RAG

```text
query
  → 从 Neo4j 现有词表推断食材/工具/分类
  → Neo4j 候选与图谱上下文
  → Chroma 语义召回
  → BM25 关键词召回
  → 按 recipe_id 转为三路排名
  → 加权 RRF
  → 图谱证据 + 文本上下文
  → DeepSeek 生成答案
```

当前实现需要冻结记录的行为：

- Chroma 召回时没有传入 Graph 候选 ID，Graph 候选主要在融合阶段获得排名提升。
- BM25 `search()` 支持 `recipe_ids`，但 Hybrid 当前调用没有传入该过滤条件。
- 当前所谓 rerank 是候选菜谱排名前移，不是独立 reranker 模型。
- Neo4j、Chroma 或 BM25 单路失败时没有编排级的逐级降级链。

## 3. 组件与初始化成本

“成本”是基于源码执行路径的定性盘点，没有进行耗时基准测试。

| 组件 | 当前创建位置/时机 | 初始化工作 | 成本与生命周期风险 |
| --- | --- | --- | --- |
| Chat Model | `model.factory` 模块导入时 | 读取密钥与 YAML，创建 OpenAI-compatible `ChatOpenAI` | 中；缺少 `DEEPSEEK_API_KEY` 会让上层导入直接失败 |
| Embedding | `model.factory` 模块导入时 | 从本地目录加载 HuggingFace/BGE 模型到 CPU | 高；模型目录缺失即导入失败，进程冷启动需要加载模型 |
| Chroma | `VectorStoreService.__init__` | 打开本地持久化 collection，绑定 Embedding | 中；普通 RAG 在 Tool 模块导入阶段创建，Hybrid 又按请求创建 Service |
| Parent store | 每次 `ParentChildRetriever.invoke` | 读取并解析 `storage/parent_documents.json` | 中；当前文件约 697 KiB，查询路径重复读取 |
| BM25 | `BM25RecipeRetriever.__init__` | 连接 Neo4j，逐菜谱重构 Document、jieba 分词、构建 `BM25Okapi` | 高；Hybrid Service 当前按请求创建，因此会重复构建 |
| Neo4j Driver | 每次 `Neo4jClient()` | 创建 Driver 并立即 `verify_connectivity()` | 中到高；Graph Tool 和 Hybrid Service 都按调用创建并关闭 |
| 普通 RAG Chain | `agent.tools.agent_tools` 模块导入时创建全局 `rag` | 创建 Chroma、Retriever、Prompt、LLM Chain | 高；导入 Agent Tool 即触发模型/Embedding/Chroma 链路 |
| Query Router | Tool 模块导入时创建全局对象 | 轻量 Python 对象；实际 auto 路由会调用聊天模型 | 低初始化、请求时有一次模型调用 |
| ReactAgent | 每个 Streamlit 浏览器会话首次使用 | 创建 `InMemorySaver`、Agent、注册 Tool 和 middleware | 中；依赖 Tool 模块已成功完成重型导入 |

## 4. 当前状态与存储

| 状态/数据 | 存放位置 | 持久性 |
| --- | --- | --- |
| UI 消息 | Streamlit `session_state` | 进程/会话级 |
| Agent 短期记忆 | `InMemorySaver` | 进程级 |
| 菜谱源文件 | `data/recipes/**/*.md` | 文件持久化 |
| 向量索引 | `storage/chroma_db/` | 本地持久化 |
| 父块正文 | `storage/parent_documents.json` | 本地持久化 |
| 入库 MD5 | `storage/recipe_md5.text` | 本地持久化 |
| 图谱 | Neo4j 外部本地服务 | 数据库持久化 |
| 日志 | `logs/agent_YYYYMMDD.log` | 本地文件 |

## 5. 当前边界与目标约束差距

| 当前行为 | 后续目标边界 | Task 00 处理 |
| --- | --- | --- |
| Streamlit 直接导入 `ReactAgent` | 前端仅使用 HTTP API/SSE/DTO | 记录，保留旧链路 |
| Agent Tool 内创建/调用底层 RAG、Graph 和外部 API | Agent → Tool Adapter → Service → Infrastructure | 记录适配点 |
| 模型与 Embedding 是模块级全局实例 | 统一资源容器管理启动/关闭 | 记录初始化成本 |
| Tool 返回自由字符串或 JSON 字符串 | 类型化请求、结果和公开错误 | 记录接口映射 |
| 检索结果使用 `node_id`/`recipe_id` 等兼容字段 | 统一 Retrieval Schema 和元数据 | 记录数据契约风险 |
| 无 API、Repository、持久化会话 | 分阶段新增，不在 Task 00 实施 | 冻结现状 |

## 6. 基线兼容原则

1. 后续迁移先用适配器包裹 `RagSummarizeService`、`HybridRagService`、`GraphRecipeRetriever` 和天气函数。
2. 在新 Service 与 API 通过回归验证之前保留 `app.py`、`ReactAgent.execute_stream()` 和现有 Tool 名称。
3. 新旧接口并行期以旧输出为兼容基线；任何有意行为变化必须在对应任务说明并测试。
4. Task 00 不修改运行时代码、依赖版本、索引或数据库。
