from langchain_core.documents import Document

from graph.neo4j_client import Neo4jClient


class GraphDataPreparationModule:
    """
    从 Neo4j 图谱中重构菜谱 Document。
    后续可以把这些 Document 送入 Chroma，形成图增强文档索引。
    """

    def __init__(self) -> None:
        self.client = Neo4jClient()

    def load_recipe_documents(self) -> list[Document]:
        recipes = self.client.execute_read(
            """
            MATCH (r:Recipe)
            OPTIONAL MATCH (r)-[:BELONGS_TO_CATEGORY]->(c:RecipeCategory)
            RETURN
                r.nodeId AS node_id,
                r.name AS recipe_name,
                r.source AS source,
                r.category AS category,
                r.difficultyText AS difficulty_text,
                c.name AS category_name
            ORDER BY r.name
            """
        )

        documents: list[Document] = []

        for recipe in recipes:
            node_id = recipe["node_id"]

            ingredients = self.client.execute_read(
                """
                MATCH (r:Recipe {nodeId: $node_id})
                      -[rel:REQUIRES]->(i:Ingredient)
                RETURN
                    i.name AS name,
                    rel.amount AS amount,
                    rel.unit AS unit,
                    rel.optional AS optional,
                    rel.raw_text AS raw_text
                ORDER BY i.name
                """,
                {"node_id": node_id},
            )

            tools = self.client.execute_read(
                """
                MATCH (r:Recipe {nodeId: $node_id})
                      -[rel:USES_TOOL]->(t:CookingTool)
                RETURN
                    t.name AS name,
                    rel.raw_text AS raw_text
                ORDER BY t.name
                """,
                {"node_id": node_id},
            )

            steps = self.client.execute_read(
                """
                MATCH (r:Recipe {nodeId: $node_id})
                      -[rel:CONTAINS_STEP]->(s:CookingStep)
                RETURN
                    s.stepNumber AS step_number,
                    s.name AS name,
                    s.description AS description
                ORDER BY rel.stepOrder
                """,
                {"node_id": node_id},
            )

            content_parts = [
                f"# {recipe['recipe_name']}",
                "",
                f"分类: {recipe.get('category_name') or recipe.get('category') or 'unknown'}",
            ]

            if recipe.get("difficulty_text"):
                content_parts.append(
                    f"预估烹饪难度: {recipe['difficulty_text']}"
                )

            if ingredients:
                content_parts.append("")
                content_parts.append("## 所需食材")

                for index, item in enumerate(ingredients, start=1):
                    amount = item.get("amount") or ""
                    unit = item.get("unit") or ""
                    optional = "，可选" if item.get("optional") else ""

                    amount_unit = (
                        f"（{amount}{unit}{optional}）"
                        if amount or unit or optional
                        else ""
                    )

                    content_parts.append(
                        f"{index}. {item['name']}{amount_unit}"
                    )

            if tools:
                content_parts.append("")
                content_parts.append("## 所需工具")

                for index, item in enumerate(tools, start=1):
                    content_parts.append(
                        f"{index}. {item['name']}"
                    )

            if steps:
                content_parts.append("")
                content_parts.append("## 制作步骤")

                for item in steps:
                    step_number = item.get("step_number") or ""
                    description = item.get("description") or ""

                    content_parts.append("")
                    content_parts.append(f"### 第{step_number}步")
                    content_parts.append(description)

            full_content = "\n".join(content_parts)

            doc = Document(
                page_content=full_content,
                metadata={
                    "node_id": node_id,
                    "recipe_id": node_id,
                    "recipe_name": recipe["recipe_name"],
                    "source": recipe.get("source"),
                    "category": recipe.get("category_name") or recipe.get("category"),
                    "difficulty_text": recipe.get("difficulty_text"),
                    "ingredients_count": len(ingredients),
                    "tools_count": len(tools),
                    "steps_count": len(steps),
                    "doc_type": "graph_recipe",
                    "content_length": len(full_content),
                },
            )

            documents.append(doc)

        return documents

    def close(self) -> None:
        self.client.close()