# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum

from pants.backend.python.subsystems.python_tool_base import LockfileRules, PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.base.deprecated import warn_or_error
from pants.engine.rules import collect_rules
from pants.option.option_types import EnumOption
from pants.util.strutil import softwrap


class LambdexLayout(Enum):
    LAMBDEX = "lambdex"


class Lambdex(PythonToolBase):
    options_scope = "lambdex"
    help = "A tool for turning .pex files into Function-as-a-Service artifacts (https://github.com/pantsbuild/lambdex)."

    default_version = "lambdex>=0.1.9"
    default_main = ConsoleScript("lambdex")
    default_requirements = [default_version]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<3.12"]

    default_lockfile_resource = ("pants.backend.python.subsystems", "lambdex.lock")
    lockfile_rules_type = LockfileRules.SIMPLE

    layout = EnumOption(
        default=LambdexLayout.LAMBDEX,
        help=softwrap(
            """
            Explicitly control the layout used for `python_awslambda` and
            `python_google_cloud_function` targets. This option exists for the transition from
            Lambdex-based layout to the plain zip layout, as recommended by cloud vendors.
            """
        ),
    )

    def warn_for_layout(self, target_alias: str) -> None:
        if self.options.is_default("layout"):
            warn_or_error(
                "2.18.0.dev0",
                f"using the Lambdex layout by default for `{target_alias}` targets",
                softwrap(
                    f"""
                    To prepare for the transition to the new layout for `{target_alias}` targets in
                    Pants 2.18, set the `[lambdex].layout` option to `lambdex` explicitly, in
                    `pants.toml`:

                        [lambdex]
                        layout = "lambdex"
                    """
                ),
            )


def rules():
    return collect_rules()
