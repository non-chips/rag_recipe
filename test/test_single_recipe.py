from pathlib import Path

from graph.recipe_parser import parse_recipe_markdown

#测试指定的菜谱文件是否能被正确解析
def main() -> None:
    data_root = Path("data/recipes").resolve()

    # 改成你实际的 md 文件路径
    file_path = Path(
        "data/recipes/drink/耙耙柑茶/耙耙柑茶.md"
    ).resolve()

    recipe = parse_recipe_markdown(
        file_path=file_path,
        data_root=data_root,
    )

    print("菜名：", recipe.name)
    print("分类：", recipe.category)
    print("难度：", recipe.difficulty_text)

    print("\n食材：")
    for item in recipe.ingredients:
        print(item)

    print("\n工具：")
    for item in recipe.tools:
        print(item)

    print("\n步骤：")
    for item in recipe.steps:
        print(item)


if __name__ == "__main__":
    main()