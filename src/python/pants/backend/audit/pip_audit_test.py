# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from unittest import mock

import pytest
import requests

from pants.backend.audit.pip_audit import audit_constraints_string

mock_ansicolors_json = {
    "info": {
        "author": "Jonathan Eunice",
    },
    "vulnerabilities": [],
}

mock_jinja2_json = {
    "info": {"author": "Armin Ronacher"},
    "vulnerabilites": [
        {
            "aliases": ["CVE-2014-0012"],
            "details": "FileSystemBytecodeCache in Jinja2 2.7.2 does not properly create temporary directories,",
            "fixed_in": ["2.7.3"],
            "id": "PYSEC-2014-82",
            "link": "https://osv.dev/vulnerability/PYSEC-2014-82",
            "source": "osv",
            "summary": None,
            "withdrawn": None,
        },
    ],
}


class MockResponse:
    def __init__(self, json_data, status_code):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data


@pytest.fixture
def pypi_session():
    return requests.Session()


def test_audit_constraint_string_no_vulns(pypi_session):
    with mock.patch.object(
        requests, "get", return_value=MockResponse(json_data=mock_ansicolors_json, status_code=200)
    ):
        vulnerabilites = audit_constraints_string("ansicolors", "1.1.8", pypi_session)
    print(vulnerabilites)
    assert not vulnerabilites


def test_audit_constraint_string_with_vulns(pypi_session):
    with mock.patch.object(
        requests, "get", return_value=MockResponse(json_data=mock_jinja2_json, status_code=200)
    ):
        vulnerabilites = audit_constraints_string("jinja2", "2.4.1", pypi_session)
    print(vulnerabilites)
    assert vulnerabilites[0].aliases == ["CVE-2014-0012"]
