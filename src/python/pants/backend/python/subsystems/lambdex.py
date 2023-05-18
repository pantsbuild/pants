# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import LockfileRules, PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules
from pants.util.strutil import softwrap


class Lambdex(PythonToolBase):
    # these aren't read automatically, but are defined for use in faas.py
    removal_hint = softwrap(
        """
        Either use `layout=\"zip\"` in `python_awslambda` or `python_google_cloud_function` targets
        to build flat packages without dynamic PEX start-up (recommended), or use `pex_binary` if dependency
        selection is required on start-up (for instance, one package is deployed to multiple
        runtimes). For a `pex_binary`, add `__pex__` to the import path for the handler: for
        example, if the handler function `func` is defined in `foo/bar.py`, configure
        `__pex__.foo.bar.func` as the handler.
        """
    )
    removal_version = "2.19.0.dev0"

    options_scope = "lambdex"
    help = softwrap(
        f"""
        A tool for turning .pex files into Function-as-a-Service artifacts (https://github.com/pantsbuild/lambdex).

        Lambdex is no longer necessary: {removal_hint}

        This will be removed in Pants {removal_version}.
        """
    )

    default_version = "lambdex>=0.1.9"
    default_main = ConsoleScript("lambdex")
    default_requirements = [default_version]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<3.12"]

    default_lockfile_resource = ("pants.backend.python.subsystems", "lambdex.lock")
    lockfile_rules_type = LockfileRules.SIMPLE


def rules():
    return collect_rules()
