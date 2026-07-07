from dataclasses import asdict
from pathlib import Path

from graph.neo4j_client import Neo4jClient
from graph.recipe_parser import parse_recipe_markdown


DELETE_OLD_STEPS = """
MATCH (r:Recipe {nodeId: $node_id})
OPTIONAL MATCH (r)-[:CONTAINS_STEP]->(s:CookingStep)
DETACH DELETE s
"""


DELETE_OLD_RELATIONS = """
MATCH (r:Recipe {nodeId: $node_id})
OPTIONAL MATCH (r)-[rel:REQUIRES|BELONGS_TO_CATEGORY|USES_TOOL]->()
DELETE rel
"""


UPSERT_RECIPE_BASE = """
MERGE (r:Recipe {nodeId: $node_id})
SET r.name = $name,
    r.preferredTerm = $name,
    r.fsn = $name,
    r.conceptType = "Recipe",
    r.filePath = $source,
    r.source = $source,
    r.category = $category,
    r.difficultyText = $difficulty_text

MERGE (c:RecipeCategory {name: $category})
SET c.preferredTerm = $category,
    c.fsn = $category,
    c.conceptType = "RecipeCategory"

MERGE (r)-[:BELONGS_TO_CATEGORY]->(c)
"""


UPSERT_INGREDIENTS = """
MATCH (r:Recipe {nodeId: $node_id})
UNWIND $ingredients AS ingredient
MERGE (i:Ingredient {name: ingredient.name})
SET i.preferredTerm = ingredient.name,
    i.conceptType = "Ingredient"

MERGE (r)-[rel:REQUIRES]->(i)
SET rel.amount = ingredient.amount,
    rel.unit = ingredient.unit,
    rel.raw_text = ingredient.raw_text,
    rel.optional = ingredient.optional
"""


UPSERT_TOOLS = """
MATCH (r:Recipe {nodeId: $node_id})
UNWIND $tools AS tool
MERGE (t:CookingTool {name: tool.name})
SET t.preferredTerm = tool.name,
    t.conceptType = "CookingTool"

MERGE (r)-[rel:USES_TOOL]->(t)
SET rel.raw_text = tool.raw_text
"""


UPSERT_STEPS = """
MATCH (r:Recipe {nodeId: $node_id})
UNWIND $steps AS step
MERGE (s:CookingStep {nodeId: step.node_id})
SET s.name = step.name,
    s.description = step.description,
    s.stepNumber = step.step_number,
    s.conceptType = "CookingStep"

MERGE (r)-[rel:CONTAINS_STEP]->(s)
SET rel.stepOrder = step.step_number
"""


GRAPH_STATS_QUERY = """
MATCH (r:Recipe)
WITH count(r) AS recipe_count

MATCH (i:Ingredient)
WITH recipe_count, count(i) AS ingredient_count

MATCH (c:RecipeCategory)
WITH recipe_count, ingredient_count, count(c) AS category_count

MATCH (s:CookingStep)
WITH recipe_count, ingredient_count, category_count, count(s) AS step_count

MATCH (t:CookingTool)
RETURN
    recipe_count,
    ingredient_count,
    category_count,
    step_count,
    count(t) AS tool_count
"""


class RecipeGraphBuilder:
    def __init__(self) -> None:
        self.client = Neo4jClient()

    def upsert_recipe(self, recipe) -> None:
        ingredients = [
            asdict(item)
            for item in recipe.ingredients
        ]

        tools = [
            asdict(item)
            for item in recipe.tools
        ]

        steps = [
            {
                "node_id": f"{recipe.node_id}_step_{step.step_number}",
                "name": step.name,
                "description": step.description,
                "step_number": step.step_number,
                "raw_text": step.raw_text,
            }
            for step in recipe.steps
        ]

        base_params = {
            "node_id": recipe.node_id,
            "name": recipe.name,
            "source": recipe.source,
            "category": recipe.category,
            "difficulty_text": recipe.difficulty_text,
        }

        # 更新单个菜谱时，先删除旧关系和旧步骤，避免修改 md 后旧数据残留
        self.client.execute_write(
            DELETE_OLD_STEPS,
            {"node_id": recipe.node_id},
        )

        self.client.execute_write(
            DELETE_OLD_RELATIONS,
            {"node_id": recipe.node_id},
        )

        self.client.execute_write(
            UPSERT_RECIPE_BASE,
            base_params,
        )

        if ingredients:
            self.client.execute_write(
                UPSERT_INGREDIENTS,
                {
                    "node_id": recipe.node_id,
                    "ingredients": ingredients,
                },
            )

        if tools:
            self.client.execute_write(
                UPSERT_TOOLS,
                {
                    "node_id": recipe.node_id,
                    "tools": tools,
                },
            )

        if steps:
            self.client.execute_write(
                UPSERT_STEPS,
                {
                    "node_id": recipe.node_id,
                    "steps": steps,
                },
            )

    def build_from_directory(
        self,
        data_dir: str,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> dict:
        data_root = Path(data_dir).resolve()

        if not data_root.exists():
            raise FileNotFoundError(
                f"菜谱数据目录不存在：{data_root}"
            )

        files = sorted(data_root.rglob("*.md"))

        if limit:
            files = files[:limit]

        total = len(files)
        success = 0
        failed = 0
        no_ingredients = 0
        no_tools = 0
        no_steps = 0

        for index, file_path in enumerate(files, start=1):
            try:
                recipe = parse_recipe_markdown(
                    file_path=file_path,
                    data_root=data_root,
                )

                if not recipe.ingredients:
                    no_ingredients += 1

                if not recipe.tools:
                    no_tools += 1

                if not recipe.steps:
                    no_steps += 1

                if dry_run:
                    print(
                        f"[DRY-RUN] [{index}/{total}] "
                        f"{recipe.name} | "
                        f"分类={recipe.category} | "
                        f"难度={recipe.difficulty_text} | "
                        f"食材={len(recipe.ingredients)} | "
                        f"工具={len(recipe.tools)} | "
                        f"步骤={len(recipe.steps)}"
                    )
                else:
                    self.upsert_recipe(recipe)
                    print(
                        f"[{index}/{total}] 已导入："
                        f"{recipe.name} | "
                        f"食材={len(recipe.ingredients)} | "
                        f"工具={len(recipe.tools)} | "
                        f"步骤={len(recipe.steps)}"
                    )

                success += 1

            except Exception as exc:
                failed += 1
                print(f"[失败] {file_path}: {exc}")

        stats = {
            "total": total,
            "success": success,
            "failed": failed,
            "no_ingredients": no_ingredients,
            "no_tools": no_tools,
            "no_steps": no_steps,
        }

        if not dry_run:
            stats["graph_statistics"] = self.get_graph_statistics()

        return stats

    def get_graph_statistics(self) -> dict:
        rows = self.client.execute_read(GRAPH_STATS_QUERY)
        return rows[0] if rows else {}

    def clear_project_graph(self) -> None:
        """
        仅删除本项目使用的几个标签，避免影响数据库中其他数据。
        """
        queries = [
            "MATCH (s:CookingStep) DETACH DELETE s",
            "MATCH (r:Recipe) DETACH DELETE r",
            "MATCH (i:Ingredient) DETACH DELETE i",
            "MATCH (c:RecipeCategory) DETACH DELETE c",
            "MATCH (t:CookingTool) DETACH DELETE t",
        ]

        for query in queries:
            self.client.execute_write(query)

    def close(self) -> None:
        self.client.close()