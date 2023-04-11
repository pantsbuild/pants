# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import LockfileRules, PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules
from pants.util.docutil import git_url


class Lambdex(PythonToolBase):
    options_scope = "lambdex"
    help = "A tool for turning .pex files into Function-as-a-Service artifacts (https://github.com/pantsbuild/lambdex)."

    default_version = "lambdex>=0.1.9"
    default_main = ConsoleScript("lambdex")
    default_requirements = [default_version]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<3.12"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "lambdex.lock")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/lambdex.lock"
    default_lockfile_url = git_url(default_lockfile_path)
    lockfile_rules_type = LockfileRules.SIMPLE


def rules():
    return collect_rules()
