# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum

from pants.backend.python.subsystems.python_tool_base import LockfileRules, PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules
from pants.option.option_types import EnumOption
from pants.util.docutil import doc_url
from pants.util.strutil import softwrap


class LambdexLayout(Enum):
    LAMBDEX = "lambdex"
    ZIP = "zip"


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
        default=LambdexLayout.ZIP,
        help=softwrap(
            """
            Explicitly control the layout used for `python_aws_lambda_function` (formerly
            `python_awslambda`) and `python_google_cloud_function` targets. This option exists for
            the transition from Lambdex-based layout to the plain zip layout, as recommended by
            cloud vendors.
            """
        ),
        removal_version="2.19.0.dev0",
        removal_hint=softwrap(
            f"""
            Remove the whole [lambdex] section, as Lambdex is deprecated and its functionality will be
            removed. If you have `layout = "zip"`, no further action is required, as you are already using
            the recommended layout.

            If you have `layout = "lambdex"`, removing the section will switch any
            `python_aws_lambda_function` (formerly `python_awslambda`) and
            `python_google_cloud_function` targets to using the `zip` layout, as recommended by
            cloud vendors.  (If you are using `python_aws_lambda_function`, you will need to also
            update the handlers configured in the cloud from `lambdex_handler.handler` to
            `lambda_function.handler`.)

            See the docs for more details:

            * {doc_url('awslambda-python#migrating-from-pants-216-and-earlier')}
            * {doc_url('google-cloud-function-python#migrating-from-pants-216-and-earlier')}
            """
        ),
    )


def rules():
    return collect_rules()
