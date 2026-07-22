import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.routing.query_router import RecipeQueryRouter


def main() -> None:
    router = RecipeQueryRouter()
    queries = [
        "西红柿鸡蛋汤需要哪些食材？",
        "西红柿鸡蛋汤怎么做？",
        "我有鸡蛋和西红柿，推荐一道简单的菜并说明为什么适合",
        "对比西红柿鸡蛋汤和西红柿豆腐汤羹哪个更适合晚餐",
        "今天很热，推荐一个适合夏天的饮品",
    ]

    for query in queries:
        print("=" * 60)
        print(query)
        print(json.dumps(router.route(query, mode="rule"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
