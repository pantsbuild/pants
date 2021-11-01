# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import sys

import pytest

from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_environment import rules as pex_environment_rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=[*pex_environment_rules(), QueryRule(PexEnvironment, input_types=())])


def test_interpreter_search_path_file_entries(rule_runner: RuleRunner) -> None:
    current_python = os.path.realpath(sys.executable)
    rule_runner.set_options(
        args=[
            f"--python-setup-interpreter-search-paths=[{current_python!r}]",
            f"--pex-bootstrap-interpreter-names=[{os.path.basename(current_python)!r}]",
        ]
    )
    pex_environment = rule_runner.request(PexEnvironment, inputs=())

    bootstrap_python = pex_environment.bootstrap_python
    assert bootstrap_python is not None
    assert current_python == bootstrap_python.path
