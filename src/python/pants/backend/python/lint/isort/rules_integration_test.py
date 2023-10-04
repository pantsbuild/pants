# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.isort.rules import IsortFieldSet, IsortRequest
from pants.backend.python.lint.isort.rules import rules as isort_rules
from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.lint.isort.subsystem import rules as isort_subsystem_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *isort_rules(),
            *isort_subsystem_rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(FmtResult, (IsortRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


GOOD_FILE = "from animals import cat, dog\n"
BAD_FILE = "from colors import green, blue\n"
FIXED_BAD_FILE = "from colors import blue, green\n"

# Note the `as` import is a new line.
NEEDS_CONFIG_FILE = "from colors import blue\nfrom colors import green as verde\n"
FIXED_NEEDS_CONFIG_FILE = "from colors import blue, green as verde\n"


def run_isort(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python.lint.isort", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    field_sets = [IsortFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.source for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            IsortRequest.Batch(
                "",
                input_sources.snapshot.files,
                partition_metadata=None,
                snapshot=input_sources.snapshot,
            ),
        ],
    )
    return fmt_result


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(Isort.default_interpreter_constraints),
)
def test_passing_source(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({"f.py": GOOD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_isort(
        rule_runner,
        [tgt],
        extra_args=[f"--isort-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )
    assert fmt_result.stdout == ""
    assert fmt_result.output == rule_runner.make_snapshot({"f.py": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing_source(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_isort(rule_runner, [tgt])
    assert fmt_result.stdout == "Fixing f.py\n"
    assert fmt_result.output == rule_runner.make_snapshot({"f.py": FIXED_BAD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.py": GOOD_FILE, "bad.py": BAD_FILE, "BUILD": "python_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    fmt_result = run_isort(rule_runner, tgts)
    assert "Fixing bad.py\n" == fmt_result.stdout
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.py": GOOD_FILE, "bad.py": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


@pytest.mark.parametrize(
    "path,extra_args", ((".isort.cfg", []), ("custom.ini", ["--isort-config=custom.ini"]))
)
def test_config_file(rule_runner: RuleRunner, path: str, extra_args: list[str]) -> None:
    rule_runner.write_files(
        {
            "f.py": NEEDS_CONFIG_FILE,
            "BUILD": "python_sources(name='t', interpreter_constraints=['==3.9.*'])",
            path: "[isort]\ncombine_as_imports=True\n",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_isort(rule_runner, [tgt], extra_args=extra_args)
    assert fmt_result.stdout == "Fixing f.py\n"
    assert fmt_result.output == rule_runner.make_snapshot({"f.py": FIXED_NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is True


def test_invalid_config_file(rule_runner: RuleRunner) -> None:
    """Reference https://github.com/pantsbuild/pants/issues/18618."""

    rule_runner.write_files(
        {
            ".isort.cfg": dedent(
                """\
        [settings]
        force_single_line = true
        # invalid setting:
        no_sections = this should be a bool, but isnt
        """
            ),
            "example.py": "from foo import bar, baz",
            "BUILD": "python_sources()",
        }
    )
    tgt = rule_runner.get_target((Address("", relative_file_path="example.py")))
    with pytest.raises(ExecutionError) as isort_error:
        run_isort(rule_runner, [tgt])
    assert any(
        re.search(r"Failed to pull configuration information from .*\.isort\.cfg", arg)
        for arg in isort_error.value.args
    )


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": NEEDS_CONFIG_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_isort(rule_runner, [tgt], extra_args=["--isort-args='--combine-as'"])
    assert fmt_result.stdout == "Fixing f.py\n"
    assert fmt_result.output == rule_runner.make_snapshot({"f.py": FIXED_NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is True


def test_stub_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.pyi": GOOD_FILE,
            "good.py": GOOD_FILE,
            "bad.pyi": BAD_FILE,
            "bad.py": BAD_FILE,
            "BUILD": "python_sources(name='t')",
        }
    )

    good_tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.pyi")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
    ]
    fmt_result = run_isort(rule_runner, good_tgts)
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.py": GOOD_FILE, "good.pyi": GOOD_FILE}
    )
    assert not fmt_result.did_change

    bad_tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.pyi")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    fmt_result = run_isort(rule_runner, bad_tgts)
    assert fmt_result.stdout == "Fixing bad.py\nFixing bad.pyi\n"
    assert fmt_result.output == rule_runner.make_snapshot(
        {"bad.py": FIXED_BAD_FILE, "bad.pyi": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change
