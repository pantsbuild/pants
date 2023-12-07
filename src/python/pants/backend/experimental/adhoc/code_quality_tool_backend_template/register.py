from pants.backend.adhoc.code_quality_tool import CodeQualityToolRuleBuilder


def rules(goal: str, target: str, name: str, scope: str):
    cfg = CodeQualityToolRuleBuilder(
        goal=goal,
        target=target,
        name=name,
        scope=scope
    )
    return cfg.rules()