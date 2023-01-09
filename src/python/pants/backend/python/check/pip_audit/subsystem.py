# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.check.pip_audit.skip_field import SkipPipAuditField
from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import ConsoleScript
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import Get, collect_rules, rule, rule_helper
from pants.engine.target import AllTargets, AllTargetsRequest
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption
from pants.util.docutil import git_url
from pants.util.logging import LogLevel


class PipAudit(PythonToolBase):
    options_scope = "pip-audit"
    name = "pip-audit"
    help = "a tool for scanning Python environments for packages with known vulnerabilities (https://pypi.org/project/pip-audit/)."

    default_version = "pip-audit>=2,<3"
    default_main = ConsoleScript("pip-audit")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.check.pip_audit", "pip_audit.lock")
    default_lockfile_path = "src/python/pants/backend/python/check/pip_audit/pip_audit.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = SkipOption("check")
    args = ArgsListOption(example="--ignore-vuln 123")
    export = ExportToolOption()


@rule_helper
async def _pip_audit_interpreter_constraints(
    python_setup: PythonSetup, pip_audit: PipAudit
) -> InterpreterConstraints:
    constraints = pip_audit.interpreter_constraints
    if pip_audit.options.is_default("interpreter_constraints"):
        all_tgts = await Get(AllTargets, AllTargetsRequest())
        # TODO: fix to use `FieldSet.is_applicable()`.
        code_constraints = InterpreterConstraints.create_from_targets(
            (tgt for tgt in all_tgts if not tgt.get(SkipPipAuditField).value), python_setup
        )
        if code_constraints is not None and code_constraints.requires_python38_or_newer(
            python_setup.interpreter_versions_universe
        ):
            constraints = code_constraints
    return constraints


class PipAuditLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = PipAudit.options_scope


@rule(
    desc="Determine pip-audit interpreter constraints (for lockfile generation)",
    level=LogLevel.DEBUG,
)
async def setup_pip_audit_lockfile(
    _: PipAuditLockfileSentinel, pip_audit: PipAudit, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    if not pip_audit.uses_custom_lockfile:
        return GeneratePythonLockfile.from_tool(
            pip_audit, use_pex=python_setup.generate_lockfiles_with_pex
        )

    constraints = await _pip_audit_interpreter_constraints(python_setup, pip_audit)

    return GeneratePythonLockfile.from_tool(
        pip_audit,
        constraints,
        use_pex=python_setup.generate_lockfiles_with_pex,
    )


class PipAuditExportSentinel(ExportPythonToolSentinel):
    pass


@rule(
    desc="Determine pip-audit interpreter constraints (for export)",
    level=LogLevel.DEBUG,
)
async def pip_audit_export(
    _: PipAuditExportSentinel, pip_audit: PipAudit, python_setup: PythonSetup
) -> ExportPythonTool:
    if not pip_audit.export:
        return ExportPythonTool(resolve_name=pip_audit.options_scope, pex_request=None)
    constraints = await _pip_audit_interpreter_constraints(python_setup, pip_audit)
    return ExportPythonTool(
        resolve_name=pip_audit.options_scope,
        pex_request=pip_audit.to_pex_request(interpreter_constraints=constraints),
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, PipAuditLockfileSentinel),
        UnionRule(ExportPythonToolSentinel, PipAuditExportSentinel),
    )
