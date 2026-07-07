from langchain_core.documents import Document

from graph.neo4j_client import Neo4jClient


class GraphRecipeRetriever:
    def __init__(self) -> None:
        self.client = Neo4jClient()

    def get_graph_statistics(self) -> dict:
        query = """
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

        rows = self.client.execute_read(query)
        return rows[0] if rows else {}

    def get_recipe_ingredients(
        self,
        recipe_name: str,
    ) -> list[dict]:
        query = """
        MATCH (r:Recipe {name: $recipe_name})
              -[rel:REQUIRES]->(i:Ingredient)
        RETURN
            r.nodeId AS recipe_id,
            r.name AS recipe_name,
            i.name AS ingredient,
            rel.amount AS amount,
            rel.unit AS unit,
            rel.optional AS optional,
            rel.raw_text AS raw_text
        ORDER BY ingredient
        """

        return self.client.execute_read(
            query,
            {"recipe_name": recipe_name},
        )

    def get_recipe_tools(
        self,
        recipe_name: str,
    ) -> list[dict]:
        query = """
        MATCH (r:Recipe {name: $recipe_name})
              -[rel:USES_TOOL]->(t:CookingTool)
        RETURN
            r.nodeId AS recipe_id,
            r.name AS recipe_name,
            t.name AS tool,
            rel.raw_text AS raw_text
        ORDER BY tool
        """

        return self.client.execute_read(
            query,
            {"recipe_name": recipe_name},
        )

    def get_recipe_steps(
        self,
        recipe_name: str,
    ) -> list[dict]:
        query = """
        MATCH (r:Recipe {name: $recipe_name})
              -[rel:CONTAINS_STEP]->(s:CookingStep)
        RETURN
            r.nodeId AS recipe_id,
            r.name AS recipe_name,
            s.stepNumber AS step_number,
            s.name AS step_name,
            s.description AS description
        ORDER BY rel.stepOrder
        """

        return self.client.execute_read(
            query,
            {"recipe_name": recipe_name},
        )

    def search_recipes_by_ingredients(
        self,
        ingredients: list[str],
        limit: int = 20,
    ) -> list[dict]:
        query = """
        MATCH (r:Recipe)-[:REQUIRES]->(i:Ingredient)
        WHERE i.name IN $ingredients
        WITH r, count(DISTINCT i) AS matched_count
        WHERE matched_count = size($ingredients)
        RETURN
            r.nodeId AS recipe_id,
            r.name AS recipe_name,
            r.source AS source,
            r.category AS category
        ORDER BY r.name
        LIMIT $limit
        """

        return self.client.execute_read(
            query,
            {
                "ingredients": ingredients,
                "limit": limit,
            },
        )

    def search_recipes_by_tool(
        self,
        tool: str,
        limit: int = 20,
    ) -> list[dict]:
        query = """
        MATCH (r:Recipe)-[:USES_TOOL]->(t:CookingTool {name: $tool})
        RETURN
            r.nodeId AS recipe_id,
            r.name AS recipe_name,
            r.source AS source,
            r.category AS category
        ORDER BY r.name
        LIMIT $limit
        """

        return self.client.execute_read(
            query,
            {
                "tool": tool,
                "limit": limit,
            },
        )

    def search_recipes_by_category(
        self,
        category: str,
        limit: int = 20,
    ) -> list[dict]:
        query = """
        MATCH (r:Recipe)-[:BELONGS_TO_CATEGORY]->(c:RecipeCategory {name: $category})
        RETURN
            r.nodeId AS recipe_id,
            r.name AS recipe_name,
            r.source AS source,
            c.name AS category
        ORDER BY r.name
        LIMIT $limit
        """

        return self.client.execute_read(
            query,
            {
                "category": category,
                "limit": limit,
            },
        )

    def get_filter_terms(self) -> dict[str, list[str]]:
        query = """
        MATCH (i:Ingredient)
        WITH collect(DISTINCT i.name) AS ingredients
        MATCH (t:CookingTool)
        WITH ingredients, collect(DISTINCT t.name) AS tools
        MATCH (c:RecipeCategory)
        RETURN
            ingredients,
            tools,
            collect(DISTINCT c.name) AS categories
        """

        rows = self.client.execute_read(query)
        if not rows:
            return {
                "ingredients": [],
                "tools": [],
                "categories": [],
            }

        return {
            "ingredients": sorted(rows[0].get("ingredients") or []),
            "tools": sorted(rows[0].get("tools") or []),
            "categories": sorted(rows[0].get("categories") or []),
        }

    def infer_filters_from_query(self, query: str) -> dict[str, list[str] | str | None]:
        terms = self.get_filter_terms()
        query_text = query or ""

        ingredients = [
            name
            for name in terms["ingredients"]
            if len(name) >= 2 and name in query_text
        ]
        tools = [
            name
            for name in terms["tools"]
            if len(name) >= 2 and name in query_text
        ]
        categories = [
            name
            for name in terms["categories"]
            if name and name in query_text
        ]

        return {
            "ingredients": ingredients,
            "tools": tools,
            "category": categories[0] if categories else None,
        }

    def search_recipe_candidates(
        self,
        ingredients: list[str] | None = None,
        tools: list[str] | None = None,
        category: str | None = None,
        recipe_names: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict]:
        query = """
        MATCH (r:Recipe)
        WHERE
            ($category IS NULL OR r.category = $category OR EXISTS {
                MATCH (r)-[:BELONGS_TO_CATEGORY]->(:RecipeCategory {name: $category})
            })
            AND (size($recipe_names) = 0 OR r.name IN $recipe_names)
            AND all(ingredient_name IN $ingredients WHERE EXISTS {
                MATCH (r)-[:REQUIRES]->(:Ingredient {name: ingredient_name})
            })
            AND all(tool_name IN $tools WHERE EXISTS {
                MATCH (r)-[:USES_TOOL]->(:CookingTool {name: tool_name})
            })
        OPTIONAL MATCH (r)-[:REQUIRES]->(i:Ingredient)
        OPTIONAL MATCH (r)-[:USES_TOOL]->(t:CookingTool)
        RETURN
            r.nodeId AS recipe_id,
            r.name AS recipe_name,
            r.source AS source,
            r.category AS category,
            r.difficultyText AS difficulty,
            collect(DISTINCT i.name) AS ingredients,
            collect(DISTINCT t.name) AS tools
        ORDER BY r.name
        LIMIT $limit
        """

        return self.client.execute_read(
            query,
            {
                "ingredients": ingredients or [],
                "tools": tools or [],
                "category": category,
                "recipe_names": recipe_names or [],
                "limit": limit,
            },
        )

    def get_recipe_evidence(self, recipe_ids: list[str]) -> list[dict]:
        if not recipe_ids:
            return []

        query = """
        MATCH (r:Recipe)
        WHERE r.nodeId IN $recipe_ids
        OPTIONAL MATCH (r)-[req:REQUIRES]->(i:Ingredient)
        OPTIONAL MATCH (r)-[:USES_TOOL]->(t:CookingTool)
        OPTIONAL MATCH (r)-[step_rel:CONTAINS_STEP]->(s:CookingStep)
        WITH
            r,
            collect(DISTINCT {
                name: i.name,
                amount: req.amount,
                unit: req.unit,
                raw_text: req.raw_text
            }) AS ingredients,
            collect(DISTINCT t.name) AS tools,
            collect(DISTINCT {
                step_number: s.stepNumber,
                name: s.name,
                description: s.description,
                order: step_rel.stepOrder
            }) AS steps
        RETURN
            r.nodeId AS recipe_id,
            r.name AS recipe_name,
            r.source AS source,
            r.category AS category,
            r.difficultyText AS difficulty,
            [item IN ingredients WHERE item.name IS NOT NULL] AS ingredients,
            [tool IN tools WHERE tool IS NOT NULL] AS tools,
            [step IN steps WHERE step.step_number IS NOT NULL] AS steps
        """

        rows = self.client.execute_read(query, {"recipe_ids": recipe_ids})
        order = {recipe_id: index for index, recipe_id in enumerate(recipe_ids)}
        return sorted(
            rows,
            key=lambda row: order.get(row.get("recipe_id"), len(order)),
        )

    def get_graph_context_documents(self, recipe_ids: list[str]) -> list[Document]:
        rows = self.get_recipe_evidence(recipe_ids)
        documents: list[Document] = []

        for row in rows:
            ingredients = []
            for item in row.get("ingredients") or []:
                name = item.get("name")
                if not name:
                    continue

                amount = item.get("amount") or ""
                unit = item.get("unit") or ""
                raw_text = item.get("raw_text") or ""
                if amount or unit:
                    ingredients.append(f"{name} {amount}{unit}".strip())
                elif raw_text:
                    ingredients.append(str(raw_text))
                else:
                    ingredients.append(str(name))

            steps = sorted(
                row.get("steps") or [],
                key=lambda item: item.get("step_number") or 0,
            )
            step_lines = [
                f"{step.get('step_number')}. {step.get('description') or step.get('name')}"
                for step in steps
                if step.get("description") or step.get("name")
            ]

            page_content = "\n".join(
                [
                    f"# {row.get('recipe_name')}",
                    f"recipe_id: {row.get('recipe_id')}",
                    f"category: {row.get('category')}",
                    f"difficulty: {row.get('difficulty')}",
                    f"ingredients: {'; '.join(ingredients)}",
                    f"tools: {'; '.join(row.get('tools') or [])}",
                    "steps:",
                    "\n".join(step_lines),
                ]
            )

            documents.append(
                Document(
                    page_content=page_content,
                    metadata={
                        "recipe_id": row.get("recipe_id"),
                        "node_id": row.get("recipe_id"),
                        "recipe_name": row.get("recipe_name"),
                        "source": row.get("source"),
                        "category": row.get("category"),
                        "difficulty": row.get("difficulty"),
                        "doc_type": "graph_context",
                    },
                )
            )

        return documents

    def hybrid_graph_retrieve(
        self,
        query: str,
        ingredients: list[str] | None = None,
        tools: list[str] | None = None,
        category: str | None = None,
        recipe_names: list[str] | None = None,
        limit: int = 50,
    ) -> dict:
        inferred_filters = self.infer_filters_from_query(query)
        filters = {
            "ingredients": ingredients if ingredients is not None else inferred_filters["ingredients"],
            "tools": tools if tools is not None else inferred_filters["tools"],
            "category": category if category is not None else inferred_filters["category"],
            "recipe_names": recipe_names or [],
        }

        has_structured_filters = any(
            [
                filters["ingredients"],
                filters["tools"],
                filters["category"],
                filters["recipe_names"],
            ]
        )

        if not has_structured_filters:
            return {
                "filters": filters,
                "candidates": [],
                "candidate_recipe_ids": [],
                "graph_context_docs": [],
            }

        candidates = self.search_recipe_candidates(
            ingredients=filters["ingredients"],
            tools=filters["tools"],
            category=filters["category"],
            recipe_names=filters["recipe_names"],
            limit=limit,
        )
        candidate_recipe_ids = [
            item["recipe_id"]
            for item in candidates
            if item.get("recipe_id")
        ]

        return {
            "filters": filters,
            "candidates": candidates,
            "candidate_recipe_ids": candidate_recipe_ids,
            "graph_context_docs": self.get_graph_context_documents(candidate_recipe_ids),
        }

    def close(self) -> None:
        self.client.close()
