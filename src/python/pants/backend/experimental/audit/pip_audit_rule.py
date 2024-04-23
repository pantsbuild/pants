from __future__ import annotations

import logging

import requests
from dataclasses import dataclass
from pants.backend.experimental.audit.audit import AuditRequest, AuditResult, AuditResults
from pants.backend.experimental.audit.pip_audit import audit_constraints_strings
from pants.backend.experimental.audit.format_results import format_results
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules.pex_requirements import (
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
)
from pants.option.option_types import DictOption
from pants.backend.python.target_types import PythonResolveField
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


logger = logging.getLogger(__name__)


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
            f"""
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
            constraints_strings=loaded_lockfile.as_constraints_strings,
            session=session,
            excludes_ids=frozenset(pypi_audit_subsystem.lockfile_vulnerability_excludes.get(resolve_name, [])),
        )
        audit_results_by_lockfile[lockfile_path] = format_results(lockfile_audit_result)

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
