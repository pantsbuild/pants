from pants.backend.adhoc import run_system_binary
from pants.backend.adhoc.target_types import SystemBinaryTarget
from pants.core.util_rules.adhoc_process_support import rules as adhoc_process_support_rules
from pants.backend.byotool.lib import ByoLinterTarget, ByoToolConfig, ByoLintGoal, ByoFmtGoal, build_rules

markdownlinter = ByoToolConfig(
    goal=ByoLintGoal,
    target='//:markdownlint_linter',
    options_scope='markdownlint',
    name="Markdown Lint",
    help="ByoTool linter for markdownlint"
)


flake8linter = ByoToolConfig(
    goal=ByoLintGoal,
    target='//:flake8_linter',
    options_scope='flake8linter',
    name="Flake8 Lint",
    help="ByoTool linter for flake8"
)

blacklinter = ByoToolConfig(
    goal=ByoFmtGoal,
    target='//:black_formatter',
    options_scope='blackformatter',
    name="Black",
    help="ByoTool linter for black"
)


def target_types():
    return [
        SystemBinaryTarget,
        ByoLinterTarget,
    ]


def rules():
    return [
        *build_rules(flake8linter),
        *adhoc_process_support_rules(),
        *run_system_binary.rules(),
    ]
