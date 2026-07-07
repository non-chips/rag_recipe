import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class IngredientData:
    name: str
    amount: str | None
    unit: str | None
    raw_text: str
    optional: bool = False


@dataclass
class ToolData:
    name: str
    raw_text: str


@dataclass
class StepData:
    step_number: int
    name: str
    description: str
    raw_text: str


@dataclass
class RecipeGraphData:
    node_id: str
    name: str
    source: str
    category: str
    difficulty_text: str | None
    ingredients: list[IngredientData]
    tools: list[ToolData]
    steps: list[StepData]


INGREDIENT_TITLES = [
    "食材",
    "用料",
    "原料",
    "材料",
    "配料",
    "主料",
    "辅料",
    "调料",
    "必需原料",
    "必备原料",
    "所需食材",
    "食材清单",
]

MIXED_MATERIAL_TOOL_TITLES = [
    "必备原料和工具",
    "必需原料和工具",
    "原料和工具",
    "食材和工具",
]

AMOUNT_TITLES = [
    "计算",
    "用量",
    "配比",
    "配方",
    "分量",
]

TOOL_TITLES = [
    "工具",
    "厨具",
    "烹饪工具",
    "所需工具",
    "必备工具",
    "使用工具",
]

STEP_TITLES = [
    "步骤",
    "做法",
    "制作步骤",
    "烹饪步骤",
    "操作步骤",
    "操作",
]

UNITS = [
    "克",
    "千克",
    "公斤",
    "斤",
    "两",
    "毫升",
    "升",
    "个",
    "只",
    "颗",
    "根",
    "片",
    "块",
    "勺",
    "茶匙",
    "汤匙",
    "杯",
    "适量",
    "少许",
]


def make_node_id(file_path: Path, data_root: Path) -> str:
    relative_path = file_path.relative_to(data_root).as_posix()
    digest = hashlib.sha256(
        relative_path.encode("utf-8")
    ).hexdigest()[:16]
    return f"recipe_{digest}"


def read_markdown(file_path: Path) -> str:
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return file_path.read_text(encoding="utf-8-sig")


def clean_markdown_link(text: str) -> str:
    """
    [蔗糖糖浆](../../condiment/蔗糖糖浆/蔗糖糖浆.md)
    -> 蔗糖糖浆
    """
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)


def clean_recipe_name(title: str) -> str:
    title = title.strip()
    title = re.sub(r"的做法$", "", title)
    title = re.sub(r"做法$", "", title)
    return title.strip()


def parse_title(content: str, file_path: Path) -> str:
    match = re.search(
        r"^#\s+(.+?)\s*$",
        content,
        flags=re.MULTILINE,
    )

    if match:
        return clean_recipe_name(match.group(1))

    return clean_recipe_name(file_path.stem)


def parse_difficulty(content: str) -> str | None:
    match = re.search(
        r"预估烹饪难度[:：]\s*([★☆]+)",
        content,
    )

    if match:
        return match.group(1).strip()

    return None


def clean_list_line(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^[-*+]\s*", "", line)
    line = re.sub(r"^\d+[\.、)]\s*", "", line)
    return line.strip()


def find_sections(
    content: str,
    titles: list[str],
) -> list[tuple[str, str]]:
    """
    查找 Markdown 二级及以上标题章节。

    返回：
    [
        ("计算", "..."),
        ("操作", "...")
    ]
    """
    if not titles:
        return []

    title_pattern = "|".join(
        re.escape(title)
        for title in titles
    )

    pattern = (
        rf"^##+\s*(?P<title>{title_pattern})\s*$"
        rf"(?P<body>.*?)(?=^##+\s+|\Z)"
    )

    matches = re.finditer(
        pattern,
        content,
        flags=re.MULTILINE | re.DOTALL,
    )

    return [
        (
            match.group("title").strip(),
            match.group("body").strip(),
        )
        for match in matches
        if match.group("body").strip()
    ]


def strip_optional_and_note(text: str) -> tuple[str, bool]:
    """
    去掉括号说明，并判断是否可选。

    示例：
    蔗糖糖浆（可选） -> 蔗糖糖浆, True
    耙耙柑（替换物请看附加内容） -> 耙耙柑, False
    """
    optional = "可选" in text

    text = re.sub(r"（.*?可选.*?）", "", text)
    text = re.sub(r"\(.*?可选.*?\)", "", text)

    text = re.sub(r"（.*?）", "", text)
    text = re.sub(r"\(.*?\)", "", text)

    return text.strip(), optional


def parse_required_materials_and_tools(
    section: str,
) -> tuple[list[IngredientData], list[ToolData]]:
    """
    解析类似：

    ## 必备原料和工具

    - 原料:
      - 耙耙柑
      - 茉莉绿茶
    - 工具
      - 搅拌机
    """
    ingredients: list[IngredientData] = []
    tools: list[ToolData] = []

    current_group: str | None = None

    for raw_line in section.splitlines():
        if not raw_line.strip():
            continue

        indent_len = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        line = clean_markdown_link(stripped)

        # 顶层列表：- 原料: / - 工具
        top_match = re.match(r"^[-*+]\s*(.+?)[:：]?\s*$", line)

        if top_match and indent_len == 0:
            title = top_match.group(1).strip()

            if title in {"原料", "食材", "材料", "配料"}:
                current_group = "ingredient"
                continue

            if title in {"工具", "厨具", "烹饪工具"}:
                current_group = "tool"
                continue

        # 子列表：  - 耙耙柑
        child_match = re.match(r"^[-*+]\s*(.+?)\s*$", stripped)

        if not child_match:
            continue

        item_text = clean_markdown_link(child_match.group(1).strip())
        item_text, optional = strip_optional_and_note(item_text)

        if not item_text:
            continue

        if current_group == "ingredient":
            ingredients.append(
                IngredientData(
                    name=item_text,
                    amount=None,
                    unit=None,
                    raw_text=child_match.group(1).strip(),
                    optional=optional,
                )
            )

        elif current_group == "tool":
            tools.append(
                ToolData(
                    name=item_text,
                    raw_text=child_match.group(1).strip(),
                )
            )

    return ingredients, tools


def parse_amount_ingredient_line(line: str) -> IngredientData | None:
    """
    解析：

    - 耙耙柑 1~2 个（200 克以上）
    - 茉莉绿茶 2~4 克
    - 冰块 60 克
    - 1 : 1 蔗糖糖浆 10 克（可选）
    """
    raw_text = line.strip()

    if not raw_text:
        return None

    # 只解析列表行，跳过“一杯分量，约 300 毫升”这类说明句
    if not raw_text.startswith(("-", "*", "+")):
        return None

    line = clean_markdown_link(clean_list_line(raw_text))

    if not line:
        return None

    optional = "可选" in line

    # 去掉括号说明，防止括号中的 200 克以上干扰主用量
    line_no_bracket = re.sub(r"（.*?）", "", line)
    line_no_bracket = re.sub(r"\(.*?\)", "", line_no_bracket)
    line_no_bracket = line_no_bracket.strip()

    unit_pattern = "|".join(
        re.escape(unit)
        for unit in UNITS
    )

    match = re.match(
        rf"^(?P<name>.+?)\s+"
        rf"(?P<amount>\d+(?:\.\d+)?(?:\s*[~～-]\s*\d+(?:\.\d+)?)?|适量|少许)\s*"
        rf"(?P<unit>{unit_pattern})?\s*$",
        line_no_bracket,
    )

    if not match:
        name, optional_from_note = strip_optional_and_note(line_no_bracket)

        if not name:
            return None

        return IngredientData(
            name=name,
            amount=None,
            unit=None,
            raw_text=raw_text,
            optional=optional or optional_from_note,
        )

    name = match.group("name").strip()
    amount = match.group("amount")
    unit = match.group("unit")

    # 特殊处理：1 : 1 蔗糖糖浆 -> 蔗糖糖浆
    name = re.sub(r"^\d+\s*[:：]\s*\d+\s*", "", name).strip()

    name, optional_from_note = strip_optional_and_note(name)

    if not name:
        return None

    return IngredientData(
        name=name,
        amount=amount,
        unit=unit,
        raw_text=raw_text,
        optional=optional or optional_from_note,
    )


def parse_amount_section(section: str) -> list[IngredientData]:
    results: list[IngredientData] = []

    for line in section.splitlines():
        item = parse_amount_ingredient_line(line)
        if item is not None:
            results.append(item)

    return results


def parse_simple_ingredient_line(line: str) -> IngredientData | None:
    raw_text = line.strip()

    if not raw_text:
        return None

    if re.fullmatch(r"[\|\-\s:：]+", raw_text):
        return None

    line = clean_markdown_link(clean_list_line(raw_text))

    if not line:
        return None

    # 跳过表头
    if line in {"食材", "原料", "材料", "用料", "名称"}:
        return None

    # 表格行
    if "|" in line:
        parts = [
            part.strip()
            for part in line.strip("|").split("|")
            if part.strip()
        ]

        if not parts:
            return None

        if parts[0] in {"食材", "原料", "材料", "用料", "名称"}:
            return None

        name = parts[0]
        amount_text = parts[1] if len(parts) > 1 else None
        name, optional = strip_optional_and_note(name)

        return IngredientData(
            name=name,
            amount=amount_text,
            unit=None,
            raw_text=raw_text,
            optional=optional,
        )

    # 优先尝试带用量解析
    amount_item = parse_amount_ingredient_line(raw_text)
    if amount_item:
        return amount_item

    name, optional = strip_optional_and_note(line)

    if not name:
        return None

    return IngredientData(
        name=name,
        amount=None,
        unit=None,
        raw_text=raw_text,
        optional=optional,
    )


def parse_simple_ingredients(section: str) -> list[IngredientData]:
    ingredients: list[IngredientData] = []

    for line in section.splitlines():
        item = parse_simple_ingredient_line(line)
        if item is not None:
            ingredients.append(item)

    return ingredients


def parse_tool_line(line: str) -> ToolData | None:
    raw_text = line.strip()

    if not raw_text:
        return None

    if re.fullmatch(r"[\|\-\s:：]+", raw_text):
        return None

    line = clean_markdown_link(clean_list_line(raw_text))

    if not line:
        return None

    if line in {"工具", "厨具", "名称"}:
        return None

    if "|" in line:
        parts = [
            part.strip()
            for part in line.strip("|").split("|")
            if part.strip()
        ]

        if not parts:
            return None

        if parts[0] in {"工具", "厨具", "名称"}:
            return None

        name = parts[0]
    else:
        name = line

    name, _ = strip_optional_and_note(name)

    if not name:
        return None

    return ToolData(
        name=name,
        raw_text=raw_text,
    )


def parse_tools(section: str) -> list[ToolData]:
    tools: list[ToolData] = []

    for line in section.splitlines():
        item = parse_tool_line(line)
        if item is not None:
            tools.append(item)

    return tools


def merge_ingredients(
    base_ingredients: list[IngredientData],
    amount_ingredients: list[IngredientData],
) -> list[IngredientData]:
    """
    合并基础原料和计算章节中的带用量原料。

    优先使用带 amount / unit 的版本。
    """
    merged: dict[str, IngredientData] = {}

    for item in base_ingredients:
        if item.name not in merged:
            merged[item.name] = item

    for item in amount_ingredients:
        old_item = merged.get(item.name)

        if old_item is None:
            merged[item.name] = item
            continue

        merged[item.name] = IngredientData(
            name=item.name,
            amount=item.amount or old_item.amount,
            unit=item.unit or old_item.unit,
            raw_text=item.raw_text or old_item.raw_text,
            optional=item.optional or old_item.optional,
        )

    return list(merged.values())


def deduplicate_tools(tools: list[ToolData]) -> list[ToolData]:
    unique: dict[str, ToolData] = {}

    for tool in tools:
        if tool.name not in unique:
            unique[tool.name] = tool

    return list(unique.values())


def parse_operation_steps(section: str) -> list[StepData]:
    """
    解析嵌套操作步骤：

    - 茉莉绿茶调配
      - 称量...
      - 往泡好的...
    - 正式调配
      - 选择一个杯子...
    """
    steps: list[StepData] = []
    current_group: str | None = None

    for raw_line in section.splitlines():
        if not raw_line.strip():
            continue

        indent_len = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        match = re.match(r"^[-*+]\s*(.+?)\s*$", stripped)
        if not match:
            continue

        text = clean_markdown_link(match.group(1).strip())
        text = text.strip()

        if not text:
            continue

        # 顶层列表作为阶段标题
        if indent_len == 0:
            current_group = text
            continue

        if current_group:
            description = f"{current_group}：{text}"
        else:
            description = text

        steps.append(
            StepData(
                step_number=len(steps) + 1,
                name=f"第{len(steps) + 1}步",
                description=description,
                raw_text=text,
            )
        )

    # 如果没有解析到嵌套步骤，则退化为普通列表步骤
    if not steps:
        for raw_line in section.splitlines():
            line = clean_list_line(raw_line)
            line = clean_markdown_link(line)

            if not line:
                continue

            if re.fullmatch(r"[\|\-\s:：]+", line):
                continue

            steps.append(
                StepData(
                    step_number=len(steps) + 1,
                    name=f"第{len(steps) + 1}步",
                    description=line,
                    raw_text=line,
                )
            )

    return steps


def parse_recipe_markdown(
    file_path: Path,
    data_root: Path,
) -> RecipeGraphData:
    file_path = file_path.resolve()
    data_root = data_root.resolve()

    content = read_markdown(file_path)

    name = parse_title(content, file_path)
    difficulty_text = parse_difficulty(content)

    relative_path = file_path.relative_to(data_root)
    category = (
        relative_path.parts[0]
        if len(relative_path.parts) > 1
        else "unknown"
    )

    base_ingredients: list[IngredientData] = []
    amount_ingredients: list[IngredientData] = []
    tools: list[ToolData] = []
    steps: list[StepData] = []

    # 1. 解析“必备原料和工具”这种混合章节
    mixed_sections = find_sections(
        content,
        MIXED_MATERIAL_TOOL_TITLES,
    )

    for _, section_body in mixed_sections:
        section_ingredients, section_tools = parse_required_materials_and_tools(
            section_body
        )
        base_ingredients.extend(section_ingredients)
        tools.extend(section_tools)

    # 2. 解析普通食材章节
    ingredient_sections = find_sections(
        content,
        INGREDIENT_TITLES,
    )

    for _, section_body in ingredient_sections:
        base_ingredients.extend(
            parse_simple_ingredients(section_body)
        )

    # 3. 解析“计算 / 用量 / 配方”章节
    amount_sections = find_sections(
        content,
        AMOUNT_TITLES,
    )

    for _, section_body in amount_sections:
        amount_ingredients.extend(
            parse_amount_section(section_body)
        )

    ingredients = merge_ingredients(
        base_ingredients,
        amount_ingredients,
    )

    # 4. 解析独立工具章节
    tool_sections = find_sections(
        content,
        TOOL_TITLES,
    )

    for _, section_body in tool_sections:
        tools.extend(
            parse_tools(section_body)
        )

    tools = deduplicate_tools(tools)

    # 5. 解析步骤 / 操作章节
    step_sections = find_sections(
        content,
        STEP_TITLES,
    )

    for _, section_body in step_sections:
        steps.extend(
            parse_operation_steps(section_body)
        )

    return RecipeGraphData(
        node_id=make_node_id(file_path, data_root),
        name=name,
        source=str(file_path),
        category=category,
        difficulty_text=difficulty_text,
        ingredients=ingredients,
        tools=tools,
        steps=steps,
    )