# 检索数据与 metadata 契约

本契约定义 Graph、Chroma、BM25 在检索服务边界交换的数据。Task 03 只提供 Schema 与兼容转换器，不改变现有检索算法或 Hybrid RAG 执行链。

## 检索模型

- `RetrievalRequest`：查询文本、可选检索策略、菜名/食材/工具/分类过滤条件、`top_k` 和 `candidate_k`。
- `RetrievalHit`：一个规范化菜谱或菜谱分块，包含统一身份、内容、来源、版本和分路得分。
- `RetrievalResult`：检索策略、命中列表、图谱证据、置信度、警告、耗时和降级标记。

规范模型位于 `recipe_assistant.schemas.retrieval`；`rag.schemas` 仅作为兼容导入路径转发同一组模型。

## 统一 metadata 字段

| 字段 | 规则 |
| --- | --- |
| `recipe_id` | 必填、非空、稳定的菜谱身份；同一菜谱在 Graph、Chroma、BM25 中必须相同 |
| `recipe_name` | 可空；标准菜名，旧数据缺失时可从来源文件名推断 |
| `source_path` | 规范来源路径；旧 `source`/`file_path` 映射至此，未知时为空字符串 |
| `parent_id` | 可空；父分块身份 |
| `chunk_id` | 可空；分块身份；旧子块可由 `recipe_id + parent_index + child_index` 确定性生成 |
| `schema_version` | metadata 结构版本，默认 `retrieval_metadata_v1` |
| `knowledge_version` | 知识内容版本；旧 `file_md5` 映射为 `md5:<value>`，未知为 `unversioned` |

`category`、`ingredients`、`tools` 是通用过滤字段。转换器会保留所有未知字段，避免影响仍读取 `node_id`、`source` 或其他旧键的链路。

## recipe_id 规则

1. 规范 `recipe_id` 优先。
2. 缺少时接受非空旧 `node_id`，并记录兼容警告。
3. 两者都缺失时默认抛出 `MissingRecipeIdError`。批量导入可显式选择 `MissingRecipeIdPolicy.SKIP`，返回 `skipped=True` 和警告，由调用方记录或隔离该条数据。
4. 查询阶段不得依据正文或 Python 进程内 `hash()` 临时生成 `recipe_id`。新数据应在 ingestion 阶段生成稳定 ID。

## 旧字段映射

| 规范字段 | 读取优先级/旧字段 |
| --- | --- |
| `recipe_id` | `recipe_id` → `node_id` |
| `recipe_name` | `recipe_name` → `name` → `title` → 来源文件名 |
| `source_path` | `source_path` → `source` → `file_path` |
| `chunk_id` | `chunk_id` → `recipe_id:parent:<parent_index>:child:<child_index>` |
| `schema_version` | `schema_version` → `chunk_schema_version` → 默认值 |
| `knowledge_version` | `knowledge_version` → `md5:<file_md5>` → `unversioned` |

转换是增补式的：原始字典会被复制，旧字段不会被删除。这样现有代码可继续读取旧键，新代码则统一读取规范键。

## 使用示例

```python
from rag.ingestion.metadata_normalizer import normalize_metadata

result = normalize_metadata(document.metadata)
document.metadata = result.metadata
```

接入现有 Graph、Chroma、BM25 写入或检索链属于后续任务，不在 Task 03 范围内。
