from __future__ import annotations

import pytest
import requests

from pants.backend.experimental.audit.pip_audit import audit_constraints_string


@pytest.fixture
def pypi_session():
    return requests.Session()


def test_audit_constraint_string_no_vulns(pypi_session):
    vulnerabilites = audit_constraints_string("ansicolors", "1.1.8", pypi_session)
    assert vulnerabilites is None


def test_audit_constraint_string_with_vulns(pypi_session):
    vulnerabilites = audit_constraints_string("jinja2", "2.4.1", pypi_session)
    assert vulnerabilites[0]["aliases"] == ["CVE-2014-0012"]
