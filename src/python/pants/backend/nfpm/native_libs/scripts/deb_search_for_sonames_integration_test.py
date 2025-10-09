# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys

import pytest

from pants.backend.python.util_rules import pex_from_targets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner

from ..rules import DebPackagesForSonames, DebSearchForSonamesRequest
from ..rules import rules as native_libs_rules
from .deb_search_for_sonames import deb_search_for_sonames

TEST_CASES = (
    pytest.param("debian", "bookworm", "amd64", ("libldap-2.5.so.0",), ("libldap-2.5-0",)),
    pytest.param("debian", "bookworm", "arm64", ("libldap-2.5.so.0",), ("libldap-2.5-0",)),
    pytest.param("ubuntu", "jammy", "amd64", ("libldap-2.5.so.0",), ("libldap-2.5-0",)),
    pytest.param("ubuntu", "jammy", "arm64", ("libldap-2.5.so.0",), ("libldap-2.5-0",)),
    pytest.param("ubuntu", "foobar", "amd64", ("libldap-2.5.so.0",), (), id="bad distro_codename"),
    pytest.param("ubuntu", "jammy", "foobar", ("libldap-2.5.so.0",), (), id="bad debian_arch"),
    pytest.param("ubuntu", "jammy", "amd64", ("foobarbaz-9.9.so.9",), (), id="bad soname"),
    pytest.param(
        "ubuntu",
        "jammy",
        "amd64",
        ("libcurl.so",),  # the search api returns a table like this:
        # ------------------------------------------- | ----------------------------------------------------------- |
        # File                                        | Packages                                                    |
        # ------------------------------------------- | ----------------------------------------------------------- |
        # /usr/lib/cupt4-2/downloadmethods/libcurl.so | libcupt4-2-downloadmethod-curl                              |
        # /usr/lib/x86_64-linux-gnu/libcurl.so        | libcurl4-gnutls-dev, libcurl4-nss-dev, libcurl4-openssl-dev |
        # ------------------------------------------- | ----------------------------------------------------------- |
        (
            "libcupt4-2-downloadmethod-curl",
            "libcurl4-gnutls-dev",
            "libcurl4-nss-dev",
            "libcurl4-openssl-dev",
        ),
        id="same file in multiple packages",
    ),
)


@pytest.mark.parametrize("distro,distro_codename,debian_arch,sonames,expected", TEST_CASES)
async def test_deb_search_for_sonames(
    distro: str,
    distro_codename: str,
    debian_arch: str,
    sonames: tuple[str, ...],
    expected: tuple[str, ...],
):
    result = await deb_search_for_sonames(distro, distro_codename, debian_arch, sonames)
    assert result == set(expected)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *pex_from_targets.rules(),
            *native_libs_rules(),
            QueryRule(DebPackagesForSonames, (DebSearchForSonamesRequest,)),
        ],
    )

    # The rule builds a pex with wheels for the pants venv.
    _py_version = ".".join(map(str, sys.version_info[:3]))

    rule_runner.set_options(
        [
            f"--python-interpreter-constraints=['CPython=={_py_version}']",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


@pytest.mark.parametrize("distro,distro_codename,debian_arch,sonames,expected", TEST_CASES)
def test_deb_search_for_sonames_rule(
    distro: str,
    distro_codename: str,
    debian_arch: str,
    sonames: tuple[str, ...],
    expected: tuple[str, ...],
    rule_runner: RuleRunner,
) -> None:
    result = rule_runner.request(
        DebPackagesForSonames,
        [DebSearchForSonamesRequest(distro, distro_codename, debian_arch, sonames)],
    )
    assert result.packages == expected
