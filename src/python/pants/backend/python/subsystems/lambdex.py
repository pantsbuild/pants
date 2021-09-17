# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.goals.lockfile import PythonLockfileRequest, PythonToolLockfileSentinel
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.docutil import git_url


class Lambdex(PythonToolBase):
    options_scope = "lambdex"
    help = "A tool for turning .pex files into Function-as-a-Service artifacts (https://github.com/pantsbuild/lambdex)."

    default_version = "lambdex==0.1.6"
    default_main = ConsoleScript("lambdex")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6,<3.10"]

    register_lockfile = True
    default_lockfile_resource = (
        "pants.backend.python.subsystems",
        "lambdex_lockfile.txt",
    )
    default_lockfile_path = "src/python/pants/backend/python/subsystems/lambdex_lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)


class LambdexLockfileSentinel(PythonToolLockfileSentinel):
    options_scope = Lambdex.options_scope


@rule
def setup_lambdex_lockfile(_: LambdexLockfileSentinel, lambdex: Lambdex) -> PythonLockfileRequest:
    return PythonLockfileRequest.from_tool(lambdex)


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, LambdexLockfileSentinel))
