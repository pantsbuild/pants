# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
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


class LambdexLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = Lambdex.options_scope


@rule
def setup_lambdex_lockfile(_: LambdexLockfileSentinel, lambdex: Lambdex) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(lambdex)


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, LambdexLockfileSentinel),
    )
