import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.hybrid_rag_service import HybridRagService


def main() -> None:
    query = "我有鸡蛋和西红柿，想做一道简单的菜"
    service = HybridRagService()

    try:
        result = service.retrieve(
            query=query,
            ingredients=["鸡蛋", "西红柿"],
        )

        print("=" * 60)
        print("混合检索测试")
        print("=" * 60)
        print(f"用户问题：{query}")
        print(f"结构化过滤条件：{result.filters}")
        print(f"Neo4j候选菜谱数量：{len(result.candidates)}")
        print(f"Chroma返回文本块数量：{len(result.text_docs)}")
        print(f"RRF融合结果数量：{len(result.fused_results)}")

        print("\n候选菜谱Top 10：")
        for row in result.candidates[:10]:
            print(
                f"- {row.get('recipe_name')} | "
                f"id={row.get('recipe_id')} | "
                f"category={row.get('category')}"
            )

        print("\nRRF融合排序：")
        for index, item in enumerate(result.fused_results, start=1):
            print(
                f"{index}. recipe_id={item.recipe_id} | "
                f"score={item.fused_score:.6f} | "
                f"sources={item.sources}"
            )

        print("\n语义排序后的文本上下文：")
        for index, doc in enumerate(result.text_docs, start=1):
            print("-" * 60)
            print(f"[{index}] recipe_id={doc.metadata.get('recipe_id')}")
            print(f"source={doc.metadata.get('source')}")
            print(doc.page_content[:300])

        print("\n图谱依据：")
        for row in result.graph_evidence:
            print("-" * 60)
            print(f"{row.get('recipe_name')} | {row.get('recipe_id')}")
            print(f"食材数：{len(row.get('ingredients') or [])}")
            print(f"工具：{row.get('tools')}")

    finally:
        service.close()


if __name__ == "__main__":
    main()
