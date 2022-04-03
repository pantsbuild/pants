# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.black.rules import BlackFieldSet, BlackRequest
from pants.backend.python.lint.black.rules import rules as black_rules
from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.black.subsystem import rules as black_subsystem_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.native_engine import Snapshot
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import (
    all_major_minor_python_versions,
    skip_unless_python38_present,
    skip_unless_python39_present,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *black_rules(),
            *black_subsystem_rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(FmtResult, (BlackRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


GOOD_FILE = 'animal = "Koala"\n'
BAD_FILE = 'name=    "Anakin"\n'
FIXED_BAD_FILE = 'name = "Anakin"\n'
NEEDS_CONFIG_FILE = "animal = 'Koala'\n"  # Note the single quotes.


def run_black(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python.lint.black", *(extra_args or ())],
        # We propagate LANG and LC_ALL to satisfy click, which black depends upon. Without this we
        # see something like the following in CI:
        #
        # RuntimeError: Click will abort further execution because Python was configured to use
        # ASCII as encoding for the environment. Consult
        # https://click.palletsprojects.com/unicode-support/ for mitigation steps.
        #
        # This system supports the C.UTF-8 locale which is recommended. You might be able to
        # resolve your issue by exporting the following environment variables:
        #
        #     export LC_ALL=C.UTF-8
        #     export LANG=C.UTF-8
        #
        env_inherit={"PATH", "PYENV_ROOT", "HOME", "LANG", "LC_ALL"},
    )
    field_sets = [BlackFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.source for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            BlackRequest(field_sets, snapshot=input_sources.snapshot),
        ],
    )
    return fmt_result


def get_snapshot(rule_runner: RuleRunner, source_files: dict[str, str]) -> Snapshot:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    digest = rule_runner.request(Digest, [CreateDigest(files)])
    return rule_runner.request(Snapshot, [digest])


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(Black.default_interpreter_constraints),
)
def test_passing(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({"f.py": GOOD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    interpreter_constraint = (
        ">=3.6.2,<3.7" if major_minor_interpreter == "3.6" else f"=={major_minor_interpreter}.*"
    )
    fmt_result = run_black(
        rule_runner,
        [tgt],
        extra_args=[f"--black-interpreter-constraints=['{interpreter_constraint}']"],
    )
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_snapshot(rule_runner, {"f.py": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_black(rule_runner, [tgt])
    assert "1 file reformatted" in fmt_result.stderr
    assert fmt_result.output == get_snapshot(rule_runner, {"f.py": FIXED_BAD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.py": GOOD_FILE, "bad.py": BAD_FILE, "BUILD": "python_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    fmt_result = run_black(rule_runner, tgts)
    assert "1 file reformatted, 1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_snapshot(
        rule_runner, {"good.py": GOOD_FILE, "bad.py": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


@pytest.mark.parametrize(
    "config_path,extra_args",
    (["pyproject.toml", []], ["custom_config.toml", ["--black-config=custom_config.toml"]]),
)
def test_config_file(rule_runner: RuleRunner, config_path: str, extra_args: list[str]) -> None:
    rule_runner.write_files(
        {
            "f.py": NEEDS_CONFIG_FILE,
            "BUILD": "python_sources(name='t')",
            config_path: "[tool.black]\nskip-string-normalization = 'true'\n",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_black(rule_runner, [tgt], extra_args=extra_args)
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_snapshot(rule_runner, {"f.py": NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is False


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": NEEDS_CONFIG_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_black(
        rule_runner, [tgt], extra_args=["--black-args='--skip-string-normalization'"]
    )
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_snapshot(rule_runner, {"f.py": NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is False


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_black(rule_runner, [tgt], extra_args=["--black-skip"])
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False


@skip_unless_python38_present
def test_works_with_python38(rule_runner: RuleRunner) -> None:
    """Black's typed-ast dependency does not understand Python 3.8, so we must instead run Black
    with Python 3.8 when relevant."""
    content = dedent(
        """\
        import datetime

        x = True
        if y := x:
            print("x is truthy and now assigned to y")


        class Foo:
            pass
        """
    )
    rule_runner.write_files(
        {"f.py": content, "BUILD": "python_sources(name='t', interpreter_constraints=['>=3.8'])"}
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_black(rule_runner, [tgt])
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_snapshot(rule_runner, {"f.py": content})
    assert fmt_result.did_change is False


@skip_unless_python39_present
def test_works_with_python39(rule_runner: RuleRunner) -> None:
    """Black's typed-ast dependency does not understand Python 3.9, so we must instead run Black
    with Python 3.9 when relevant."""
    content = dedent(
        """\
        @lambda _: int
        def replaced(x: bool) -> str:
            return "42" if x is True else "1/137"
        """
    )
    rule_runner.write_files(
        {"f.py": content, "BUILD": "python_sources(name='t', interpreter_constraints=['>=3.9'])"}
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_black(rule_runner, [tgt])
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_snapshot(rule_runner, {"f.py": content})
    assert fmt_result.did_change is False


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
    fmt_result = run_black(rule_runner, good_tgts)
    assert "2 files left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_snapshot(
        rule_runner, {"good.pyi": GOOD_FILE, "good.py": GOOD_FILE}
    )
    assert not fmt_result.did_change

    bad_tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.pyi")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    fmt_result = run_black(rule_runner, bad_tgts)
    assert "2 files reformatted" in fmt_result.stderr
    assert fmt_result.output == get_snapshot(
        rule_runner, {"bad.pyi": FIXED_BAD_FILE, "bad.py": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change
