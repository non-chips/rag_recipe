import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recipe_assistant.agents.router import BusinessRouter


def main() -> None:
    router = BusinessRouter()
    queries = [
        "西红柿鸡蛋汤需要哪些食材？",
        "西红柿鸡蛋汤怎么做？",
        "我有鸡蛋和西红柿，推荐一道简单的菜",
        "根据今天的天气推荐晚饭",
    ]
    for query in queries:
        decision = router.route(query)
        print(json.dumps(decision.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
