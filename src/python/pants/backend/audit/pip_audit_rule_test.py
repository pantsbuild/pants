# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap

import pytest

from pants.backend.audit.audit import AuditResult, AuditResults
from pants.backend.audit.format_results import format_results
from pants.backend.audit.pip_audit import VulnerabilityData
from pants.backend.audit.pip_audit_rule import PypiAuditRequest
from pants.backend.audit.pip_audit_rule import rules as pip_audit_rules
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonRequirementTarget
from pants.backend.python.util_rules.pex_requirements import rules as pex_requirements_rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *PythonSetup.rules(),
            *pip_audit_rules(),
            *pex_requirements_rules(),
            QueryRule(AuditResults, (PypiAuditRequest,)),
        ],
        target_types=[PythonRequirementTarget],
    )


setuptools_poetry_lockfile = r"""
# This lockfile was autogenerated by Pants. To regenerate, run:
#
#    ./pants generate-lockfiles --resolve=setuptools
#
# --- BEGIN PANTS LOCKFILE METADATA: DO NOT EDIT OR REMOVE ---
# {
#   "version": 2,
#   "valid_for_interpreter_constraints": [
#     "CPython>=3.7"
#   ],
#   "generated_with_requirements": [
#     "setuptools==54.1.2"
#   ]
# }
# --- END PANTS LOCKFILE METADATA ---

setuptools==54.1.2; python_version >= "3.6" \
    --hash=sha256:dd20743f36b93cbb8724f4d2ccd970dce8b6e6e823a13aa7e5751bb4e674c20b \
    --hash=sha256:ebd0148faf627b569c8d2a1b20f5d3b09c873f12739d71c7ee88f037d5be82ff
"""
report_a = format_results(
    {
        'setuptools==54.1.2; python_version >= "3.6"': [
            VulnerabilityData(
                vuln_id="GHSA-r9hx-vwmv-q579",
                details=textwrap.dedent(
                    """
                    Python Packaging Authority (PyPA)'s setuptools is a library designed to
                    facilitate packaging Python projects. Setuptools version 65.5.0 and earlier
                    could allow remote attackers to cause a denial of service by fetching
                    malicious HTML from a PyPI package or custom PackageIndex page due to a
                    vulnerable Regular Expression in `package_index`. This has been patched
                    in version 65.5.1.
                """
                ),
                fixed_in=["65.5.1"],
                aliases=["CVE-2022-40897"],
                link="https://osv.dev/vulnerability/GHSA-r9hx-vwmv-q579",
                summary=None,
                withdrawn=None,
            ),
            VulnerabilityData(
                vuln_id="PYSEC-2022-43012",
                details=textwrap.dedent(
                    """
                    Python Packaging Authority (PyPA) setuptools before 65.5.1 allows remote
                    attackers to cause a denial of service via HTML in a crafted package or
                    custom PackageIndex page. There is a Regular Expression Denial of Service
                    (ReDoS) in package_index.py.
                """
                ),
                fixed_in=["65.5.1"],
                aliases=["CVE-2022-40897"],
                link="https://osv.dev/vulnerability/PYSEC-2022-43012",
                summary=None,
                withdrawn=None,
            ),
        ]
    }
)


def test_pip_audit(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "a.lock": setuptools_poetry_lockfile,
        }
    )
    rule_runner.set_options(
        [
            "--python-resolves={'a': 'a.lock'}",
            "--python-enable-resolves",
        ],
    )
    result = rule_runner.request(AuditResults, [PypiAuditRequest(field_sets=())])
    assert result == AuditResults(
        results=(AuditResult(resolve_name="a", lockfile="a.lock", report=report_a),),
        auditor_name="pypi_auditor",
    )
