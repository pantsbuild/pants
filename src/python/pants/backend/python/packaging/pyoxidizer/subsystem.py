# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import ConsoleScript
from pants.backend.python.util_rules.pex_requirements import GeneratePythonToolLockfileSentinel
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption
from pants.util.docutil import git_url
from pants.util.strutil import softwrap


class PyOxidizer(PythonToolBase):
    options_scope = "pyoxidizer"
    name = "PyOxidizer"
    help = softwrap(
        """
        The PyOxidizer utility for packaging Python code in a Rust binary
        (https://pyoxidizer.readthedocs.io/en/stable/pyoxidizer.html).

        Used with the `pyoxidizer_binary` target.
        """
    )

    default_version = "pyoxidizer==0.18.0"
    default_main = ConsoleScript("pyoxidizer")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.8,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.packaging.pyoxidizer", "pyoxidizer.lock")
    default_lockfile_path = "src/python/pants/backend/python/packaging/pyoxidizer/pyoxidizer.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    args = ArgsListOption(example="--release")


class PyoxidizerLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = PyOxidizer.options_scope


@rule
def setup_lockfile_request(
    _: PyoxidizerLockfileSentinel, pyoxidizer: PyOxidizer, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(
        pyoxidizer, use_pex=python_setup.generate_lockfiles_with_pex
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, PyoxidizerLockfileSentinel),
    )
