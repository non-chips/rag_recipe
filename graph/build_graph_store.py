import argparse

from graph.graph_builder import RecipeGraphBuilder
from graph.schema import create_schema


def main() -> None:
    parser = argparse.ArgumentParser(
        description="构建 Neo4j 菜谱知识图谱"
    )

    parser.add_argument(
        "--data-dir",
        default="data/recipes",
        help="Markdown 菜谱目录",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理前 N 个文件，用于测试",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析并打印，不写入 Neo4j",
    )

    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="清空本项目图谱后重建",
    )

    args = parser.parse_args()

    if not args.dry_run:
        create_schema()

    builder = RecipeGraphBuilder()

    try:
        if args.rebuild and not args.dry_run:
            print(
                "警告：即将删除本项目创建的 "
                "Recipe / Ingredient / RecipeCategory / "
                "CookingStep / CookingTool 图谱数据。"
            )
            confirm = input("请输入 YES 确认：")

            if confirm != "YES":
                print("已取消 rebuild。")
                return

            builder.clear_project_graph()
            print("旧图谱数据已清空。")

        stats = builder.build_from_directory(
            data_dir=args.data_dir,
            limit=args.limit,
            dry_run=args.dry_run,
        )

        print("\n图谱构建统计：")
        for key, value in stats.items():
            print(f"{key}: {value}")

    finally:
        builder.close()


if __name__ == "__main__":
    main()