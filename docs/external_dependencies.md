# 外部依赖与可 Mock 点

## 1. 概览

当前核心链路同时依赖远程模型、远程天气接口、本地 Embedding、本地 Chroma 和 Neo4j。依赖由模块全局初始化与请求级创建混合管理，因此测试替身需要放在构造边界或网络/Driver 边界。

## 2. 环境变量

| 环境变量 | 使用位置 | 必需性 | 缺失行为 | 可 Mock 点 |
| --- | --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | `model/factory.py` | 当前 Agent/RAG 导入必需 | `model.factory` 导入阶段抛 `ValueError` | Patch `ChatModelFactory.generator` 或注入 fake chat model |
| `AMAP_API_KEY` | 天气 Tool | 仅天气/定位请求必需 | 调用天气函数时失败；公开 Tool 转为失败 JSON 或“未知城市” | Patch `_gaode_get`，优先 Mock `WeatherService`（后续） |
| `NEO4J_URI` | `Neo4jClient` | Graph/Hybrid/BM25 必需 | 构造 `Neo4jClient` 时抛 `ValueError` | 注入 fake Graph Adapter/Client |
| `NEO4J_USERNAME` | `Neo4jClient` | Graph/Hybrid/BM25 必需 | 同上 | 同上 |
| `NEO4J_PASSWORD` | `Neo4jClient` | Graph/Hybrid/BM25 必需 | 同上 | 同上 |
| `NEO4J_DATABASE` | `Neo4jClient` | 可选，默认 `neo4j` | 使用默认数据库 | fake Client 可忽略或记录数据库名 |

配置文件声明了 `chat_api_key_env` 和 `gaode_api_key_env`，但当前聊天模型工厂仍直接读取固定的 `DEEPSEEK_API_KEY`。密钥不得写入 YAML、文档示例实值或日志。

## 3. 网络与进程外服务

| 依赖 | 地址/协议 | 当前调用 | 超时/重试 | 失败影响 | 推荐 Mock 边界 |
| --- | --- | --- | --- | --- | --- |
| DeepSeek OpenAI-compatible | `https://api.deepseek.com` | 路由、Agent、普通/Hybrid 答案生成 | Chat model timeout 60s，max_retries 2 | 主 Agent、路由或答案生成失败 | Fake `BaseChatModel`；不要在单元测试访问真实 API |
| 高德地图 | `https://restapi.amap.com` | 地理编码、IP 定位、实时天气 | YAML 默认 8s，无显式重试 | 天气能力降级，当前返回失败 JSON/未知城市 | Mock `_gaode_get` 或后续 `WeatherService` |
| 公网 IP 服务 | `api.ipify.org`、`ipv4.icanhazip.com` | 为高德 IP 定位获取公网 IPv4 | 每源 5s，顺序尝试 | 可继续用空 IP 请求高德，最终可能未知城市 | Mock `_get_public_ip` |
| Neo4j | Bolt，地址来自 `NEO4J_URI` | 图谱构建、Graph 查询、Hybrid 候选、BM25 语料 | Driver connect timeout 10s，构造时 verify | Graph/Hybrid/BM25 初始化失败 | Fake `Neo4jClient`/Graph Adapter；集成测试使用显式标记的测试库 |

Task 00 不访问这些远程服务，不写入 Neo4j。

## 4. 本地模型与存储

| 依赖 | 默认路径 | 读/写 | 当前职责 | 失败行为 | 可 Mock 点 |
| --- | --- | --- | --- | --- | --- |
| BGE Embedding | `model/embeddingmodels/bge-small-zh-v1.5` | 读 | 查询与入库向量化 | 导入 `model.factory` 时抛 `FileNotFoundError` | Fake `Embeddings`，返回固定维度向量 |
| Chroma | `storage/chroma_db` | 查询和入库写 | 子块向量索引 | 构造/查询异常向上传播 | Fake Vector Retriever 或临时 collection |
| 父块存储 | `storage/parent_documents.json` | 每次查询读；入库写 | child→parent 上下文回取 | 文件不存在时退回 child；JSON 损坏会抛异常 | 临时 JSON fixture / fake parent store |
| MD5 清单 | `storage/recipe_md5.text` | 入库读写 | 跳过已处理文件 | 不存在时创建 | 临时路径 fixture |
| 菜谱知识 | `data/recipes/**/*.md` | 读 | Chroma 入库与图谱构建源 | 目录不存在时向量扫描为空或图谱构建报错 | 小型 Markdown fixture |
| 日志目录 | `logs/` | 模块导入及运行写 | 调试日志 | 权限问题可能导致 logger 导入失败 | 临时 log path / NullHandler（后续装配） |

当前本地状态盘点：

- `data/recipes` 下扫描到 323 个 Markdown 文件。
- `storage/chroma_db` 已存在。
- `storage/parent_documents.json` 已存在，约 697 KiB。
- `storage/recipe_md5.text` 已存在。
- `model/embeddingmodels` 目录已存在；具体模型可用性仍需通过最小导入检查验证。

## 5. Python 包依赖

| 能力 | 主要包 |
| --- | --- |
| UI | `streamlit` |
| Agent/Graph | `langchain`、`langchain-core`、`langgraph`、`langgraph-prebuilt` |
| 模型 API | `langchain-openai`、`python-dotenv` |
| 本地 Embedding | `langchain-huggingface`、`sentence-transformers`、`tokenizers` |
| 向量库 | `langchain-chroma`、`chromadb` |
| 文档 | `langchain-community`、`langchain-text-splitters`、`pypdf` |
| 图数据库 | 源码直接导入 `neo4j`；当前 `requirements.txt` 未显式列出该包 |
| 关键词检索 | `jieba`、`rank-bm25` |
| 配置 | `PyYAML` |

冻结风险：`python-dotenv`、`sentence-transformers` 没有固定版本，`neo4j` 没有显式出现在 `requirements.txt`。Task 00 只记录，不调整版本。

## 6. 建议的测试替身层级

| 测试层级 | 使用真实组件 | 必须 Mock/禁用 |
| --- | --- | --- |
| 单元：路由规则、解析、RRF | 纯 Python 逻辑、内存 Document | DeepSeek、Neo4j、高德、Chroma、本地大模型 |
| 单元：Service | Service 与 Schema | Infrastructure Adapter、聊天模型 |
| 集成：Vector | 临时 Chroma、fake Embedding、小型父块 fixture | DeepSeek、Neo4j、高德 |
| 集成：Graph | 显式配置的测试 Neo4j 或 fake Client | 生产 Neo4j、真实天气、真实 LLM |
| 集成：Weather | HTTP 响应 fixture | 公网 IP 与高德真实网络 |
| E2E smoke | 可选择真实本地 Embedding/Chroma，使用测试配置 | 默认不访问付费/生产服务；真实服务测试需显式 opt-in |

## 7. 外部依赖隔离优先级

1. 把 Chat Model、Embedding、Chroma、Neo4j Driver、BM25 建造移动到统一资源容器。
2. 让 Tool 依赖类型化 Service，而不是导入模块级全局实例。
3. 让 `RetrievalService` 捕获单路 Infrastructure 错误并按策略降级，同时记录 warning 和 fallback。
4. 将高德与公网 IP 封装进 `WeatherService`/HTTP Client，统一超时、错误码和 Mock。
5. 所有集成测试通过配置显式启用外部服务；默认测试套件应离线、可重复。
