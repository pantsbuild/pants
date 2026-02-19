# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys

import pytest

from pants.backend.nfpm.native_libs.deb.rules import (
    DebPackagesForSonames,
    DebSearchForSonamesRequest,
)
from pants.backend.nfpm.native_libs.deb.rules import rules as native_libs_deb_rules
from pants.backend.nfpm.native_libs.deb.test_utils import TEST_CASES
from pants.backend.python.util_rules import pex_from_targets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *pex_from_targets.rules(),
            *native_libs_deb_rules(),
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


@pytest.mark.parametrize(
    "distro,distro_codename,debian_arch,sonames,expected_raw,expected_raw_from_best_so_files",
    TEST_CASES,
)
def test_deb_search_for_sonames_rule(
    distro: str,
    distro_codename: str,
    debian_arch: str,
    sonames: tuple[str, ...],
    expected_raw: dict[str, dict[str, list[str]]],
    expected_raw_from_best_so_files: None | dict[str, dict[str, list[str]]],
    rule_runner: RuleRunner,
) -> None:
    for from_best_so_files, _expected_raw in (
        (False, expected_raw),
        (True, expected_raw_from_best_so_files or expected_raw),
    ):
        expected = DebPackagesForSonames.from_dict(_expected_raw)
        result = rule_runner.request(
            DebPackagesForSonames,
            [
                DebSearchForSonamesRequest(
                    distro,
                    distro_codename,
                    debian_arch,
                    sonames,
                    from_best_so_files=from_best_so_files,
                )
            ],
        )
        assert result == expected
