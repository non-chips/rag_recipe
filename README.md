# 智能菜谱推荐助手

> 基于 LangChain Agent + GraphRAG 的智能菜谱问答与推荐系统

---

## 使用必看

请先配置好相关运行环境，并按需设置以下环境变量：

- `DEEPSEEK_API_KEY`：用于调用 DeepSeek 对话模型
- `AMAP_API_KEY`：用于调用高德地图天气与定位服务

同时，本项目默认使用本地 HuggingFace Embedding 模型：

```text
model/embeddingmodels/bge-small-zh-v1.5
```

请确保该目录下已经放置好对应的本地嵌入模型文件，否则向量检索模块无法正常初始化。

---

## 项目简介

**智能菜谱推荐助手** 是一个面向菜谱问答、食材查询、做法检索和个性化菜品推荐的 AI Agent 应用。系统以 Streamlit 构建轻量级网页对话界面，后端基于 LangChain Agent 组织工具调用，并融合Neo4j 数据库图谱、BM25 关键词检索和 Chroma 向量检索，实现更贴近真实菜谱知识库场景的混合检索能力。

系统支持以下核心能力：

- **菜谱知识库问答**：从本地 Markdown 菜谱文件中检索相关内容，回答食材、步骤、做法、工具、分类等问题。
- **普通 RAG 检索**：将菜谱文档切分为父子块后写入 Chroma，基于语义相似度召回相关菜谱上下文。
- **图谱结构化检索**：将菜谱解析为 Recipe、Ingredient、CookingStep、CookingTool、RecipeCategory 等节点，并写入 Neo4j 数据库。
- **混合检索 Hybrid RAG**：先用 Neo4j 根据食材、工具、分类等结构化条件筛选候选菜谱，再融合 Chroma 语义检索、BM25 关键词检索和图谱上下文，通过 RRF 进行排序。
- **查询路由**：通过路由工具判断用户问题适合普通 RAG、图谱检索还是混合检索，提升复杂问题下的检索策略选择能力。
- **天气辅助推荐**：调用高德地图 API 获取用户位置和实时天气，用于“根据今天的天气推荐菜谱”等场景。
- **流式响应与会话记忆**：前端支持逐字流式输出，Agent 使用 thread_id 保存短期对话状态。

---

## 系统架构

```text
┌──────────────────────────────────────────────┐
│              Streamlit 前端 app.py            │
│  - 聊天输入  - 历史消息展示  - 流式响应输出     │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│          LangChain Agent react_agent.py       │
│  - ReAct / Tool Calling                       │
│  - thread_id 会话状态管理                      │
│  - InMemorySaver 短期记忆                      │
└──────────────────────┬───────────────────────┘
                       │
        ┌──────────────┼─────────────────┐
        ▼              ▼                 ▼
┌──────────────┐ ┌──────────────┐ ┌────────────────┐
│  Agent Tools │ │  Middleware  │ │ Query Router    │
│ agent_tools  │ │ middleware   │ │ routing/        │
└──────┬───────┘ └──────────────┘ └────────────────┘
       │
       ├──────────────────────────────────────────────┐
       │                                              │
       ▼                                              ▼
┌──────────────────────┐                  ┌──────────────────────┐
│ 普通 RAG              │                  │ 外部服务工具           │
│ rag/rag_service.py    │                  │ 高德天气 / IP 定位      │
│ rag/vector_store.py   │                  │ get_weather            │
└──────────┬───────────┘                  │ get_user_location      │
           │                              └──────────────────────┘
           ▼
┌──────────────────────────────────────────────┐
│ Chroma 向量库 storage/chroma_db               │
│ - 子块向量检索                                │
│ - 父块上下文返回                              │
│ - MD5 去重避免重复入库                         │
└──────────────────────────────────────────────┘


┌──────────────────────────────────────────────┐
│                 Hybrid RAG                    │
│         rag/hybrid_rag_service.py             │
│                                              │
│  1. Neo4j 图谱筛选候选菜谱                    │
│  2. Chroma 语义检索                           │
│  3. BM25 关键词检索                           │
│  4. RRF 融合排序                              │
│  5. LLM 基于图谱依据 + 文本上下文生成回答       │
└──────────────────────┬───────────────────────┘
                       │
        ┌──────────────┼─────────────────┐
        ▼              ▼                 ▼
┌──────────────┐ ┌──────────────┐ ┌────────────────┐
│ Neo4j Graph  │ │ Chroma Vector│ │ BM25 Retriever │
│ graph/       │ │ rag/         │ │ rag/retrieval/ │
└──────────────┘ └──────────────┘ └────────────────┘
```

---

## 目录结构

```text
rag_recipe/
├── app.py
│   └── Streamlit 前端入口，负责页面展示、聊天输入和流式输出
│
├── agent/
│   ├── react_agent.py
│   │   └── Agent 核心入口，注册模型、工具、中间件和会话记忆
│   │
│   ├── tools/
│   │   ├── agent_tools.py
│   │   │   └── Agent 可调用工具，包括 RAG、Hybrid RAG、图谱查询、天气定位等
│   │   └── middleware.py
│   │       └── 工具调用监控与模型调用前日志
│   │
│   └── routing/
│       ├── __init__.py
│       └── query_router.py
│           └── 菜谱问题路由器，用于判断问题类型和推荐检索策略
│
├── rag/
│   ├── rag_service.py
│   │   └── 普通 RAG 问答服务
│   │
│   ├── hybrid_rag_service.py
│   │   └── 图谱 + 向量 + BM25 的混合检索问答服务
│   │
│   ├── vector_store.py
│   │   └── Chroma 向量库管理、文档加载、父子块切分、MD5 去重
│   │
│   └── retrieval/
│       ├── bm25_retriever.py
│       │   └── BM25 关键词检索
│       ├── fusion.py
│       │   └── RRF 融合排序
│       └── __init__.py
│
├── graph/
│   ├── build_graph_store.py
│   │   └── 图谱构建入口脚本
│   │
│   ├── graph_builder.py
│   │   └── 将解析后的菜谱数据写入 Neo4j
│   │
│   ├── graph_data_preparation.py
│   │   └── 图谱数据预处理
│   │
│   ├── graph_retriever.py
│   │   └── Neo4j 图谱查询与结构化候选菜谱召回
│   │
│   ├── neo4j_client.py
│   │   └── Neo4j 数据库连接与读写封装
│   │
│   ├── recipe_parser.py
│   │   └── 从 Markdown 菜谱中解析菜名、食材、工具、步骤等结构化信息
│   │
│   └── schema.py
│       └── 菜谱图谱数据结构定义
│
├── model/
│   └── factory.py
│       └── LLM 与 Embedding 本地模型
│
├── prompts/
│   └── 存放 Agent 主提示词、RAG 提示词、Hybrid RAG 提示词等
│
├── config/
│   ├── agent.yml
│   │   └── 高德 API、IP 查询源等 Agent 工具配置
│   │
│   ├── rag.yml
│   │   └── DeepSeek 模型、本地 Embedding 模型路径等配置
│   │
│   ├── chroma.yml
│   │   └── Chroma、文档路径、chunk 参数、RRF 权重等配置
│   │
│   ├── graph.yml
│   │   └── Neo4j、菜谱解析字段标题、批处理参数等图谱配置
│   │
│   └── prompts.yml
│       └── 提示词路径配置
│
├── data/
│   └── recipes/
│
├── test/
│   └── 测试脚本
│
├── utils/
│   └── 配置加载、日志、文件处理、路径处理等通用工具
│
├── requirements.txt
```

---

## 环境依赖

### Python 版本

建议使用：

```text
Python 3.10+
```

安装依赖：

```bash
python -m pip install -r requirements.txt
```

---

## 配置说明

### 1. 配置 DeepSeek API Key

本项目默认通过兼容 OpenAI 接口的方式调用 DeepSeek 模型，需要配置环境变量：

```bash
export DEEPSEEK_API_KEY="your_deepseek_api_key"
```

配置文件位置：

```text
config/rag.yml
```

默认配置示例：

```yaml
chat_model_name: deepseek-v4-flash
chat_base_url: https://api.deepseek.com
chat_api_key_env: DEEPSEEK_API_KEY
temperature: 0.2
```

---

### 2. 配置本地 Embedding 模型

项目默认使用本地 BGE 中文向量模型：

```yaml
embedding_provider: huggingface
embedding_model_path: model/embeddingmodels/bge-small-zh-v1.5
embedding_device: cpu
embedding_offline: true
```

请将模型文件放入：

```text
model/embeddingmodels/bge-small-zh-v1.5
```

---

### 3. 配置高德地图 API Key

天气与定位功能依赖高德地图 API。请配置环境变量：

```bash
export AMAP_API_KEY="your_amap_api_key"
```

对应配置文件：

```text
config/agent.yml
```

默认配置示例：

```yaml
gaode_api_key_env: AMAP_API_KEY
gaode_base_url: https://restapi.amap.com
gaode_timeout: 8
public_ip_timeout: 5
public_ip_sources:
  - https://api.ipify.org
  - https://ipv4.icanhazip.com
```

---

### 4. 配置 Chroma 向量库

对应配置文件：

```text
config/chroma.yml
```

核心配置示例：

```yaml
collection_name: recipe_chunks
persist_directory: storage/chroma_db
data_path: data/recipes
md5_hex_store: storage/recipe_md5.text
parent_doc_store: storage/parent_documents.json

allow_knowledge_file_type:
  - md

chunk_size: 600
chunk_overlap: 80
parent_chunk_size: 1800
parent_chunk_overlap: 200

k: 5
child_k: 15
chroma_k: 20
bm25_k: 20
rrf_k: 60
rrf_weights:
  graph: 1.2
  chroma: 1.0
  bm25: 0.9
```

说明：

- `data_path`：菜谱知识库路径
- `persist_directory`：Chroma 持久化目录
- `md5_hex_store`：已入库文档的 MD5 记录文件
- `parent_doc_store`：父块文档存储文件
- `chunk_size` / `chunk_overlap`：子块切分参数
- `parent_chunk_size` / `parent_chunk_overlap`：父块切分参数
- `rrf_weights`：混合检索中 graph / chroma / bm25 三路结果的融合权重

---

### 5. 配置 Neo4j 图数据库

对应配置文件：

```text
config/graph.yml
```

默认配置示例：

```yaml
data_path: data/recipes
database: neo4j
batch_size: 50
```

同时需要根据 `graph/neo4j_client.py` 中的读取方式配置 Neo4j 连接信息。通常需要准备以下信息：

```text
NEO4J_URI
NEO4J_USERNAME
NEO4J_PASSWORD
```

实际环境变量名称请以项目中的 `neo4j_client.py` 为准。

---

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/non-chips/rag_recipe.git
cd rag_recipe
```

### 2. 安装依赖

```bash
python -m pip install -r requirements.txt
```

### 3. 配置环境变量

Linux / macOS：

```bash
export DEEPSEEK_API_KEY="your_deepseek_api_key"
export AMAP_API_KEY="your_amap_api_key"
```

Windows PowerShell：

```powershell
setx DEEPSEEK_API_KEY "your_deepseek_api_key"
setx AMAP_API_KEY "your_amap_api_key"
```

重新打开终端后生效。

### 4. 准备本地 Embedding 模型

将 `bge-small-zh-v1.5` 放入：

```text
model/embeddingmodels/bge-small-zh-v1.5
```

### 5. 构建向量知识库

可以直接运行向量库构建脚本：

```bash
python rag/vector_store.py
```

该步骤会：

1. 扫描 `data/recipes` 下的 Markdown 菜谱文件
2. 计算文件 MD5，跳过已经入库的文档
3. 对菜谱文档进行父子块切分
4. 将子块写入 Chroma
5. 将父块内容保存到 `storage/parent_documents.json`

### 6. 构建 Neo4j 菜谱图谱

请先启动 Neo4j 数据库，并配置好连接信息，然后运行：

```bash
python graph/build_graph_store.py
```

该步骤会从 `data/recipes` 中解析菜谱，并构建图谱节点和关系。

### 7. 启动应用

```bash
streamlit run app.py
```

浏览器打开后即可进入聊天界面。

默认地址通常为：

```text
http://localhost:8501
```

---

## RAG 检索机制

普通 RAG 主要由以下模块组成：

```text
rag/vector_store.py
rag/rag_service.py
```

处理流程：

```text
Markdown 菜谱文件
        │
        ▼
文件加载与 MD5 去重
        │
        ▼
Parent-Child 文档切分
        │
        ├── Parent Chunk：较长上下文，用于最终回答
        │
        └── Child Chunk：较短文本块，用于向量相似度匹配
        │
        ▼
写入 Chroma 向量库
        │
        ▼
用户提问
        │
        ▼
检索相关 Child Chunk
        │
        ▼
根据 parent_id 找回 Parent Chunk
        │
        ▼
LLM 基于上下文生成回答
```

---

## 图谱构建机制

图谱模块位于：

```text
graph/
```

主要目标是将 Markdown 菜谱解析为结构化图数据。

典型节点包括：

| 节点类型 | 含义 |
| -------- | --- |
| `Recipe` | 菜谱 |
| `Ingredient` | 食材 |
| `CookingStep` | 烹饪步骤 |
| `CookingTool` | 烹饪工具 |
| `RecipeCategory` | 菜谱分类 |

典型关系包括：

| 关系类型 | 含义 |
| ------- | ---- |
| `REQUIRES` | 菜谱需要某种食材 |
| `CONTAINS_STEP` | 菜谱包含某个制作步骤 |
| `USES_TOOL` | 菜谱使用某种工具 |
| `BELONGS_TO_CATEGORY` | 菜谱属于某个分类 |

---

## Hybrid RAG 混合检索机制

混合检索模块位于：

```text
rag/hybrid_rag_service.py
```

它的核心思想是：

> 用图谱做结构化筛选，用向量检索做语义匹配，用 BM25 做关键词补充，再用 RRF 统一排序。

整体流程如下：

```text
用户问题
  │
  ▼
图谱过滤 Graph Filter
  │
  ├── 抽取问题中出现的食材、工具、分类、菜名等条件
  ├── 在 Neo4j 中筛选候选 Recipe
  └── 生成图谱结构化依据
  │
  ▼
三路召回
  │
  ├── Graph Context：图谱候选菜谱上下文
  ├── Chroma：语义向量检索结果
  └── BM25：关键词检索结果
  │
  ▼
RRF 融合排序
  │
  ▼
选出 Top-K 菜谱与上下文
  │
  ▼
LLM 生成最终回答
```

---

## 中间件机制

Agent 中间件位于：

```text
agent/tools/middleware.py
```

目前包含两个主要功能：

```text
monitor_tool
├── 记录工具调用名称
├── 记录工具调用参数
├── 记录工具调用成功状态
└── 工具失败时输出错误日志

log_before_model
├── 记录模型调用前的消息数量
└── 记录最新一条消息内容
```

该机制便于调试 Agent 的工具调用链路，尤其适合排查：

- Agent 是否调用了正确工具；
- 工具入参是否符合预期；
- 工具是否执行成功；
- 多轮对话中消息状态是否正常。

---

## 参考

本项目仅供学习与参考使用。感谢[zhisaotong-Agent](https://github.com/bamboo-moon/zhisaotong-Agent)的代码框架以及优秀的rag教程项目[all-in-rag](https://github.com/datawhalechina/all-in-rag)。
