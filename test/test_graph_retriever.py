#测试图查询功能是否正常

from graph.graph_retriever import GraphRecipeRetriever


def main() -> None:
    retriever = GraphRecipeRetriever()

    try:
        print("图谱统计：")
        print(retriever.get_graph_statistics())

        print("\n查询耙耙柑茶的食材：")
        for row in retriever.get_recipe_ingredients("耙耙柑茶"):
            print(row)

        print("\n查询耙耙柑茶的工具：")
        for row in retriever.get_recipe_tools("耙耙柑茶"):
            print(row)

        print("\n查询耙耙柑茶的步骤：")
        for row in retriever.get_recipe_steps("耙耙柑茶"):
            print(row)

        print("\n查询包含耙耙柑和茉莉绿茶的菜谱：")
        for row in retriever.search_recipes_by_ingredients(
            ["耙耙柑", "茉莉绿茶"]
        ):
            print(row)

        print("\n查询使用搅拌机的菜谱：")
        for row in retriever.search_recipes_by_tool("搅拌机"):
            print(row)

    finally:
        retriever.close()


if __name__ == "__main__":
    main()