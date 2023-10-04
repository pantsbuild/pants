# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.dependency_inference import parse_python_dependencies
from pants.backend.python.framework.django import detect_apps
from pants.backend.python.framework.django.detect_apps import DjangoApps
from pants.backend.python.target_types import PythonSourceTarget
from pants.backend.python.util_rules import pex
from pants.core.util_rules import stripped_source_files
from pants.engine.environment import EnvironmentName
from pants.testutil.python_interpreter_selection import (
    PY_27,
    PY_39,
    skip_unless_all_pythons_present,
    skip_unless_python27_present,
    skip_unless_python37_present,
    skip_unless_python38_present,
    skip_unless_python39_present,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap


@pytest.fixture
def rule_runner() -> RuleRunner:
    ret = RuleRunner(
        rules=[
            *parse_python_dependencies.rules(),
            *stripped_source_files.rules(),
            *pex.rules(),
            *detect_apps.rules(),
            QueryRule(DjangoApps, [EnvironmentName]),
        ],
        target_types=[PythonSourceTarget],
    )
    ret.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return ret


def assert_apps_detected(
    rule_runner: RuleRunner,
    constraints1: str,
    constraints2: str = "",
) -> None:
    constraints2 = constraints2 or constraints1
    if "3." in constraints1:
        py3_only = "async def i_will_parse_on_python3_not_on_python2():\n  pass"
    else:
        py3_only = ""
    if "2.7" in constraints2:
        py2_only = "print 'I will parse on Python 2.7, not on Python 3'"
    else:
        py2_only = ""
    rule_runner.write_files(
        {
            "path/to/app1/BUILD": softwrap(
                f"""\
                {py3_only}

                python_source(
                  source="apps.py",
                  interpreter_constraints=['{constraints1}'],
                )
                """
            ),
            "path/to/app1/apps.py": softwrap(
                """\
                class App1AppConfig(AppConfig):
                    name = "path.to.app1"
                    label = "app1"
                """
            ),
            "another/path/app2/BUILD": softwrap(
                f"""\
                python_source(
                  source="apps.py",
                  interpreter_constraints=['{constraints2}'],
                )
                """
            ),
            "another/path/app2/apps.py": softwrap(
                f"""\
                {py2_only}

                class App2AppConfig(AppConfig):
                    name = "another.path.app2"
                    label = "app2_label"
                """
            ),
            "some/app3/BUILD": softwrap(
                f"""\
                python_source(
                  source="apps.py",
                  interpreter_constraints=['{constraints1}'],
                )
                """
            ),
            "some/app3/apps.py": softwrap(
                """\
                class App3AppConfig(AppConfig):
                    name = "some.app3"
                    # No explicit label, should default to app3.
                """
            ),
        }
    )
    result = rule_runner.request(
        DjangoApps,
        [],
    )
    assert result == DjangoApps(
        FrozenDict({"app1": "path.to.app1", "app2_label": "another.path.app2", "app3": "some.app3"})
    )


@skip_unless_python27_present
def test_works_with_python2(rule_runner: RuleRunner) -> None:
    assert_apps_detected(rule_runner, constraints1="CPython==2.7.*")


@skip_unless_python37_present
def test_works_with_python37(rule_runner: RuleRunner) -> None:
    assert_apps_detected(rule_runner, constraints1="CPython==3.7.*")


@skip_unless_python38_present
def test_works_with_python38(rule_runner: RuleRunner) -> None:
    assert_apps_detected(rule_runner, constraints1="CPython==3.8.*")


@skip_unless_python39_present
def test_works_with_python39(rule_runner: RuleRunner) -> None:
    assert_apps_detected(rule_runner, constraints1="CPython==3.9.*")


@skip_unless_all_pythons_present(PY_27, PY_39)
def test_partitioning_by_ics(rule_runner: RuleRunner) -> None:
    assert_apps_detected(rule_runner, constraints1="CPython==3.9.*", constraints2="CPython==2.7.*")
