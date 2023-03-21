from __future__ import annotations

import logging

import requests
from dataclasses import dataclass
from pants.backend.experimental.audit.audit import AuditRequest, AuditResult, AuditResults
from pants.backend.experimental.audit.pip_audit import audit_constraints_strings
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules.pex_requirements import (
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
)
from pants.backend.python.target_types import PythonResolveField
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)

# TODO: Do I actually need my own? There must already be a fieldset for lockfiles, presumably I could use that.
@dataclass(frozen=True)
class PypiAuditFieldSet(FieldSet):
    required_fields = (PythonResolveField,)


class PypiAuditRequest(AuditRequest):
    field_set_type = PypiAuditFieldSet
    tool_name = "pypi-audit"


@rule(desc="Audit lockfiles with pypi vulnerabilities database.", level=LogLevel.DEBUG)
async def pypi_audit(request: PypiAuditRequest, python_setup: PythonSetup) -> AuditResults:
    if not PythonSetup.enable_resolves:
        # TODO: Fail, we need lockfiles.
        pass
    session = requests.Session()
    lockfile_paths = python_setup.resolves.items()
    audit_results_by_lockfile = {}
    for resolve_name, lockfile_path in lockfile_paths:
        lockfile = Lockfile(
            url=lockfile_path,
            url_description_of_origin=f"the resolve `{resolve_name}`",
            resolve_name=resolve_name,
        )
        loaded_lockfile = await Get(LoadedLockfile, LoadedLockfileRequest(lockfile))
        lockfile_audit_result = audit_constraints_strings(
            loaded_lockfile.as_constraints_strings, session
        )
        raise ValueError(lockfile_audit_result)
        audit_results_by_lockfile[lockfile_path] = lockfile_audit_result

    return AuditResults(
        results=tuple(
            AuditResult(lockfile=lockfile, report=resolve)
            for resolve, lockfile in lockfile_paths
        ),
        auditor_name="pypi_auditor",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(AuditRequest, PypiAuditRequest),
    ]
