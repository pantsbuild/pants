# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from pants.backend.experimental.audit.audit import AuditRequest, AuditResult, AuditResults
from pants.backend.experimental.audit.format_results import format_results
from pants.backend.experimental.audit.pip_audit import audit_constraints_strings
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
from pants.backend.python.util_rules.pex_requirements import (
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.option.option_types import DictOption
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class MissingLockfileException(Exception):
    pass


@dataclass(frozen=True)
class PypiAuditFieldSet(FieldSet):
    required_fields = (PythonResolveField,)


class PypiAuditRequest(AuditRequest):
    field_set_type = PypiAuditFieldSet
    tool_id = "pypi-audit"


class PypiAuditSubsystem(Subsystem):
    name = "pypi-audit"
    options_scope = "pypi-audit"
    help = "Configuration for the pypi audit rule."

    lockfile_vulnerability_excludes = DictOption(
        help=softwrap(
            """
            A mapping of logical names of Python lockfiles to a list of excluded vulnerability IDs.
            """
        ),
    )


@rule(desc="Audit lockfiles with pypi vulnerabilities database.", level=LogLevel.DEBUG)
async def pypi_audit(
    request: PypiAuditRequest,
    pypi_audit_subsystem: PypiAuditSubsystem,
    python_setup: PythonSetup,
) -> AuditResults:
    if not PythonSetup.enable_resolves:
        raise MissingLockfileException("This tool requires lockfiles be enabled.")
    session = requests.Session()
    lockfile_paths = python_setup.resolves.items()
    lockfiles = [
        Lockfile(
            url=lockfile_path,
            url_description_of_origin=f"the resolve `{resolve_name}`",
            resolve_name=resolve_name,
        )
        for resolve_name, lockfile_path in lockfile_paths
    ]
    loaded_lockfiles = await MultiGet(
        Get(LoadedLockfile, LoadedLockfileRequest, LoadedLockfileRequest(lockfile))
        for lockfile in lockfiles
    )
    audit_results_by_lockfile = {}
    for loaded_lockfile in loaded_lockfiles:
        lockfile_audit_result = audit_constraints_strings(
            constraints_strings=loaded_lockfile.as_constraints_strings,
            session=session,
            excludes_ids=frozenset(
                pypi_audit_subsystem.lockfile_vulnerability_excludes.get(
                    loaded_lockfile.original_lockfile.resolve_name, []
                )
            ),
        )
        audit_results_by_lockfile[loaded_lockfile.lockfile_path] = format_results(
            lockfile_audit_result
        )

    return AuditResults(
        results=tuple(
            AuditResult(
                resolve_name=resolve_name,
                lockfile=lockfile,
                report=audit_results_by_lockfile[lockfile],
            )
            for resolve_name, lockfile in lockfile_paths
        ),
        auditor_name="pypi_auditor",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(AuditRequest, PypiAuditRequest),
    ]
