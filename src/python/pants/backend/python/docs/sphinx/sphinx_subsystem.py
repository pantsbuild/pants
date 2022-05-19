# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.docutil import git_url


class SphinxSubsystem(PythonToolBase):
    options_scope = "sphinx"
    name = "sphinx"
    help = "The Python documentation generator (https://www.sphinx-doc.org/en/master/index.html)."

    default_version = "sphinx>=4.5.0,<4.6"
    default_extra_requirements = ["setuptools"]
    default_main = ConsoleScript("sphinx-build")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.docs.sphinx", "sphinx.lock")
    default_lockfile_path = "src/python/pants/backend/python/docs/sphinx/sphinx.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    export = ExportToolOption()


class SphinxLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = SphinxSubsystem.options_scope


@rule
def setup_sphinx_lockfile(
    _: SphinxLockfileSentinel, sphinx: SphinxSubsystem, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(
        sphinx, use_pex=python_setup.generate_lockfiles_with_pex
    )


class SphinxExportSentinel(ExportPythonToolSentinel):
    pass


@rule
def sphinx_export(_: SphinxExportSentinel, sphinx: SphinxSubsystem) -> ExportPythonTool:
    if not sphinx.export:
        return ExportPythonTool(resolve_name=sphinx.options_scope, pex_request=None)
    return ExportPythonTool(resolve_name=sphinx.options_scope, pex_request=sphinx.to_pex_request())


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, SphinxLockfileSentinel),
        UnionRule(ExportPythonToolSentinel, SphinxExportSentinel),
    )
