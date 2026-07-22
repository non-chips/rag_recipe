# 食谱助手 Skill 编写规范

Skill 是按业务 Route、显式信号和风险加载的行为约束，不是菜谱知识。菜名、食材、用量、步骤、营养数值等事实仍进入既有知识数据源；`SKILL.md` 不得加入 Chroma、BM25、Neo4j 或知识文档摄取目录。

## 目录与 frontmatter

每个 Skill 使用独立目录，目录名必须与 `name` 相同：

```text
skills/
└── allergy_safe_recommendation/
    └── SKILL.md
```

推荐 frontmatter：

```yaml
---
name: allergy_safe_recommendation
version: "1.0.0"
description: Apply conservative safety behavior when allergies are present.
routes:
  - RECIPE_RECOMMENDATION
  - COMPLEX
signals:
  - ALLERGY_MENTIONED
priority: 100
risk: HIGH
requires: []
---
```

`intents` 可作为规范示例的兼容别名，但新文件应使用 `routes`。版本使用 SemVer。名称只能包含小写字母、数字和下划线。`requires` 只能引用注册表内其他 Skill，不能自引用或形成循环。

## 选择语义

Registry 先匹配 Route，再匹配信号和有效风险，最后按优先级、风险、名称稳定排序。过敏和排除食材信号会把有效风险提升到 `HIGH`，替换请求提升到 `MEDIUM`。依赖 Skill 会随被选 Skill 一并加载。

正文会进入行为 Prompt 上下文，且每段都带有 `name@version`。Trace 或 Prompt 审计应保存 `selected_skill_refs`，例如：

```text
allergy_safe_recommendation@1.0.0
```

## 安全边界

- Skill 只能描述行为和工作流，不能充当菜谱或营养事实来源。
- Skill 不直接访问数据库、检索器、天气服务或外部 API。
- Skill 不授予 Tool 权限；实际调用仍经过 Tool Registry 与 Service。
- Skill 不能替代或放宽 `ConstraintService` 的过敏原、排除食材、厨具和时间硬约束。
- 天气只能来自天气 Tool Adapter；不可猜测城市或实时天气。
- 营养 Skill 不能把不完整数据写成精确值，也不能给出医疗诊断。

## 变更检查

新增或升级 Skill 时：

1. 更新 SemVer，说明行为差异。
2. 添加 Route、信号、风险和优先级选择测试。
3. 测试低证据、工具不可用和硬约束冲突。
4. 确认 Prompt 上下文记录 `name@version`。
5. 确认文件不在任何知识摄取目录或向量索引清单中。
