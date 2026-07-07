#agent可调用的业务工具

import os
from utils.logger_handler import logger
from langchain_core.tools import tool
from rag.rag_service import RagSummarizeService
from utils.config_handler import agent_conf
import json
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from dotenv import load_dotenv
from graph.graph_retriever import GraphRecipeRetriever
from rag.hybrid_rag_service import HybridRagService
from agent.routing.query_router import RecipeQueryRouter
import re

load_dotenv()  # Load environment variables from .env file

rag = RagSummarizeService()
query_router = RecipeQueryRouter()

_IPV4_RE = re.compile(
    r"^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\."
    r"(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\."
    r"(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\."
    r"(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$"
)

def _is_valid_ipv4(ip: str) -> bool:
    return bool(_IPV4_RE.match(ip or ""))

def _get_public_ip() -> str:
    # 可在agent.yml里覆盖
    ip_sources = agent_conf.get("public_ip_sources", [
        "https://ipv4.icanhazip.com",
    ])
    timeout = float(agent_conf.get("public_ip_timeout", 3))
    for source in ip_sources:
        try:
            with urlopen(source, timeout=timeout) as resp:
                ip = resp.read().decode("utf-8").strip()
                if _is_valid_ipv4(ip):
                    return ip
        except Exception:
            continue

    return ""

GAODE_BASE_URL = agent_conf.get("gaode_base_url")
GAODE_TIMEOUT = float(agent_conf.get("gaode_timeout"))

#从高德api获取信息
def _gaode_get(path: str, params: dict) -> dict:
    gaode_key = _get_amap_api_key()

    query = dict(params)
    query["key"] = gaode_key

    url = (
        f"{GAODE_BASE_URL}{path}?"
        f"{urlencode(query)}"
    )

    try:
        with urlopen(
            url,
            timeout=GAODE_TIMEOUT,
        ) as response:
            data = response.read().decode("utf-8")

        result = json.loads(data)

        if result.get("status") != "1":
            raise RuntimeError(
                "高德接口返回失败："
                f"info={result.get('info')}，"
                f"infocode={result.get('infocode')}"
            )

        return result

    except HTTPError as exc:
        raise RuntimeError(
            f"高德 HTTP 错误：{exc.code}"
        ) from exc

    except URLError as exc:
        raise RuntimeError(
            f"高德网络错误：{exc.reason}"
        ) from exc

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "高德接口返回了无法解析的 JSON"
        ) from exc
    

#通过环境变量获取高德api
def _get_amap_api_key() -> str:
    env_name = agent_conf.get(
        "gaode_api_key_env",
        "AMAP_API_KEY",
    )

    api_key = os.getenv(env_name, "").strip()

    if not api_key:
        raise ValueError(
            f"未读取到高德环境变量 {env_name}，"
            "请检查 Windows 用户环境变量并重新启动终端。"
        )

    return api_key


def _resolve_city_to_adcode(city: str) -> tuple[str, str]:
    geo = _gaode_get("/v3/geocode/geo", {"address": city})
    if geo.get("status") != "1" or not geo.get("geocodes"):
        raise RuntimeError(f"城市解析失败: {geo.get('info', 'unknown')}")

    first = geo["geocodes"][0]
    adcode = first.get("adcode")
    if not adcode:
        raise RuntimeError("城市解析成功但未返回adcode")

    resolved_city = first.get("city") or first.get("district") or city
    if isinstance(resolved_city, list):
        resolved_city = "".join(resolved_city)

    return str(resolved_city), str(adcode)


@tool(
    description=(
        "获取指定城市的实时天气。"
        "输入城市名称，返回城市、天气、温度、湿度、风向和风力。"
    )
)
def get_weather(city: str) -> str:
    if not city or not city.strip():
        return json.dumps(
            {
                "success": False,
                "message": "未提供城市名称",
            },
            ensure_ascii=False,
        )

    try:
        resolved_city, adcode = _resolve_city_to_adcode(
            city.strip()
        )

        weather = _gaode_get(
            "/v3/weather/weatherInfo",
            {
                "city": adcode,
                "extensions": "base",
                "output": "JSON",
            },
        )

        lives = weather.get("lives", [])

        if not lives:
            return json.dumps(
                {
                    "success": False,
                    "city": resolved_city,
                    "message": "未获取到实时天气",
                },
                ensure_ascii=False,
            )

        live = lives[0]

        result = {
            "success": True,
            "city": resolved_city,
            "adcode": adcode,
            "weather": live.get("weather", "未知"),
            "temperature_c": live.get(
                "temperature",
                "未知",
            ),
            "humidity_percent": live.get(
                "humidity",
                "未知",
            ),
            "wind_direction": live.get(
                "winddirection",
                "未知",
            ),
            "wind_power": live.get(
                "windpower",
                "未知",
            ),
            "report_time": live.get(
                "reporttime",
                "未知",
            ),
        }

        return json.dumps(
            result,
            ensure_ascii=False,
        )

    except Exception as exc:
        logger.error(
            f"[get_weather]天气查询失败 "
            f"city={city} err={exc}",
            exc_info=True,
        )

        return json.dumps(
            {
                "success": False,
                "city": city,
                "message": "天气查询失败",
            },
            ensure_ascii=False,
        )


@tool(description="获取用户所在城市的名称，以纯字符串形式返回")
def get_user_location() -> str:
    try:
        public_ip = _get_public_ip()
        params = {"ip": public_ip} if public_ip else {}
        ip_info = _gaode_get("/v3/ip", params)

        if ip_info.get("status") != "1":
            logger.warning(
                f"[get_user_location]高德返回失败 info={ip_info.get('info')} "
                f"infocode={ip_info.get('infocode')} ip={public_ip or 'none'}"
            )
            return "未知城市"

        city = ip_info.get("city", "")
        province = ip_info.get("province", "")

        if isinstance(city, list):
            city = "".join(city)
        if isinstance(province, list):
            province = "".join(province)

        city = str(city).strip()
        province = str(province).strip()

        if city:
            return city
        if province:
            return province

        logger.warning(
            f"[get_user_location]空城市信息 info={ip_info.get('info')} "
            f"infocode={ip_info.get('infocode')} ip={public_ip or 'none'} raw={ip_info}"
        )
        return "未知城市"

    except Exception as e:
        logger.error(f"[get_user_location]定位失败 err={str(e)}")
        return "未知城市"



@tool(description="从菜谱知识库中检索菜谱、食材、制作步骤、烹饪方法和相关参考资料。")
def rag_summarize(query: str) -> str:
    return rag.rag_summarize(query)


@tool(
    description=(
        "智能查询路由工具。输入用户原始菜谱问题，返回 JSON 路由决策，"
        "包括 strategy、query_type、complexity_score、relation_density_score、"
        "是否需要多跳推理、因果分析、对比分析，以及推荐下一步应调用的检索策略。"
        "当问题复杂、包含多个条件、需要推荐/对比/解释，或不确定该使用哪个检索工具时，应先调用本工具。"
    )
)
def route_recipe_query(query: str) -> str:
    result = query_router.route(query=query, use_llm=True)
    return json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    )


@tool(
    description=(
        "混合检索菜谱知识库：先用 Neo4j 根据食材、工具、分类等结构化信息筛选候选菜谱，"
        "再用 Chroma 在候选菜谱内做语义检索排序，最后结合图谱依据和菜谱文本生成答案。"
        "适合带有明确条件的菜谱推荐、对比和做法查询。"
    )
)
def hybrid_rag_summarize(query: str) -> str:
    service = HybridRagService()
    try:
        return service.hybrid_summarize(query)
    finally:
        service.close()



@tool(
    description=(
        "从Neo4j菜谱图谱中查询结构化菜谱信息。"
        "适合查询：某道菜需要哪些食材、某道菜需要哪些工具、"
        "某道菜有哪些步骤、哪些菜同时包含多个食材、"
        "哪些菜使用某种工具、某分类下有哪些菜。"
    )
)
def graph_recipe_search(query_type: str, query_value: str) -> str:
    """
    query_type 可选：
    - recipe_ingredients: 查询某道菜的食材，query_value为菜名
    - recipe_tools: 查询某道菜的工具，query_value为菜名
    - recipe_steps: 查询某道菜的步骤，query_value为菜名
    - ingredients: 查询同时包含多个食材的菜，query_value用逗号分隔，如 耙耙柑,茉莉绿茶
    - tool: 查询使用某工具的菜，query_value为工具名，如 搅拌机
    - category: 查询某分类下的菜，query_value为分类名，如 drink
    - statistics: 查询图谱统计，query_value可为空
    """
    retriever = GraphRecipeRetriever()

    try:
        if query_type == "recipe_ingredients":
            result = retriever.get_recipe_ingredients(
                query_value.strip()
            )

        elif query_type == "recipe_tools":
            result = retriever.get_recipe_tools(
                query_value.strip()
            )

        elif query_type == "recipe_steps":
            result = retriever.get_recipe_steps(
                query_value.strip()
            )

        elif query_type == "ingredients":
            ingredients = [
                item.strip()
                for item in query_value.split(",")
                if item.strip()
            ]

            result = retriever.search_recipes_by_ingredients(
                ingredients=ingredients,
                limit=20,
            )

        elif query_type == "tool":
            result = retriever.search_recipes_by_tool(
                tool=query_value.strip(),
                limit=20,
            )

        elif query_type == "category":
            result = retriever.search_recipes_by_category(
                category=query_value.strip(),
                limit=20,
            )

        elif query_type == "statistics":
            result = retriever.get_graph_statistics()

        else:
            result = {
                "error": (
                    "不支持的 query_type。可选值："
                    "recipe_ingredients, recipe_tools, recipe_steps, "
                    "ingredients, tool, category, statistics"
                )
            }

        return json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )

    finally:
        retriever.close()

# if __name__ == '__main__':
#     print(get_weather(get_user_location()))
