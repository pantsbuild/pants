from pants.backend.adhoc import run_system_binary
from pants.backend.adhoc.target_types import SystemBinaryTarget
from pants.core.util_rules.adhoc_process_support import rules as adhoc_process_support_rules
from pants.backend.code_quality_tool.lib import CodeQualityToolTarget, ByoToolConfig, build_rules


def target_types(**kwargs):
    return [
        SystemBinaryTarget,
        CodeQualityToolTarget,
    ]


def rules(**kwargs):
    config = ByoToolConfig(**kwargs)
    return [
        *build_rules(config),
        *adhoc_process_support_rules(),
        *run_system_binary.rules(),
    ]
