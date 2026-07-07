from graph.neo4j_client import Neo4jClient


SCHEMA_QUERIES = [
    """
    CREATE CONSTRAINT recipe_node_id_unique IF NOT EXISTS
    FOR (r:Recipe)
    REQUIRE r.nodeId IS UNIQUE
    """,
    """
    CREATE CONSTRAINT ingredient_name_unique IF NOT EXISTS
    FOR (i:Ingredient)
    REQUIRE i.name IS UNIQUE
    """,
    """
    CREATE CONSTRAINT category_name_unique IF NOT EXISTS
    FOR (c:RecipeCategory)
    REQUIRE c.name IS UNIQUE
    """,
    """
    CREATE CONSTRAINT step_node_id_unique IF NOT EXISTS
    FOR (s:CookingStep)
    REQUIRE s.nodeId IS UNIQUE
    """,
    """
    CREATE CONSTRAINT tool_name_unique IF NOT EXISTS
    FOR (t:CookingTool)
    REQUIRE t.name IS UNIQUE
    """,
]


def create_schema() -> None:
    with Neo4jClient() as client:
        for query in SCHEMA_QUERIES:
            client.execute_write(query)

    print("Neo4j 图谱约束创建完成。")


if __name__ == "__main__":
    create_schema()