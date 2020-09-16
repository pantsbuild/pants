# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List, Optional, Sequence, Tuple

import pytest

from pants.backend.python.lint.black.rules import BlackFieldSet, BlackRequest
from pants.backend.python.lint.black.rules import rules as black_rules
from pants.backend.python.target_types import PythonLibrary
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules.pants_environment import PantsEnvironment
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.python_interpreter_selection import skip_unless_python38_present
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *black_rules(),
            QueryRule(LintResults, (BlackRequest, OptionsBootstrapper, PantsEnvironment)),
            QueryRule(FmtResult, (BlackRequest, OptionsBootstrapper, PantsEnvironment)),
            QueryRule(SourceFiles, (SourceFilesRequest, OptionsBootstrapper, PantsEnvironment)),
        ],
        target_types=[PythonLibrary],
    )


GOOD_SOURCE = FileContent("good.py", b'animal = "Koala"\n')
BAD_SOURCE = FileContent("bad.py", b'name=    "Anakin"\n')
FIXED_BAD_SOURCE = FileContent("bad.py", b'name = "Anakin"\n')
# Note the single quotes, which Black does not like by default. To get Black to pass, it will
# need to successfully read our config/CLI args.
NEEDS_CONFIG_SOURCE = FileContent("needs_config.py", b"animal = 'Koala'\n")


def make_target(
    rule_runner: RuleRunner,
    source_files: List[FileContent],
    *,
    name: str = "target",
    interpreter_constraints: Optional[str] = None,
) -> Target:
    for source_file in source_files:
        rule_runner.create_file(source_file.path, source_file.content.decode())
    rule_runner.add_to_build_file(
        "", f"python_library(name='{name}', compatibility={repr(interpreter_constraints)})\n"
    )
    return rule_runner.get_target(Address("", target_name=name))


def run_black(
    rule_runner: RuleRunner,
    targets: List[Target],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[str] = None,
    skip: bool = False,
) -> Tuple[Sequence[LintResult], FmtResult]:
    args = ["--backend-packages=pants.backend.python.lint.black"]
    if config is not None:
        rule_runner.create_file(relpath="pyproject.toml", contents=config)
        args.append("--black-config=pyproject.toml")
    if passthrough_args:
        args.append(f"--black-args='{passthrough_args}'")
    if skip:
        args.append("--black-skip")
    options_bootstrapper = create_options_bootstrapper(args=args)
    field_sets = [BlackFieldSet.create(tgt) for tgt in targets]
    pants_env = PantsEnvironment()
    lint_results = rule_runner.request(
        LintResults, [BlackRequest(field_sets), options_bootstrapper, pants_env]
    )
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
            options_bootstrapper,
            pants_env,
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            BlackRequest(field_sets, prior_formatter_result=input_sources.snapshot),
            options_bootstrapper,
            pants_env,
        ],
    )
    return lint_results.results, fmt_result


def get_digest(rule_runner: RuleRunner, source_files: List[FileContent]) -> Digest:
    return rule_runner.request(Digest, [CreateDigest(source_files)])


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    lint_results, fmt_result = run_black(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert "1 file would be left unchanged" in lint_results[0].stderr
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE])
    assert fmt_result.did_change is False


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results, fmt_result = run_black(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "1 file would be reformatted" in lint_results[0].stderr
    assert "1 file reformatted" in fmt_result.stderr
    assert fmt_result.output == get_digest(rule_runner, [FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    lint_results, fmt_result = run_black(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "1 file would be reformatted, 1 file would be left unchanged" in lint_results[0].stderr
    assert "1 file reformatted, 1 file left unchanged", fmt_result.stderr
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    targets = [
        make_target(rule_runner, [GOOD_SOURCE], name="good"),
        make_target(rule_runner, [BAD_SOURCE], name="bad"),
    ]
    lint_results, fmt_result = run_black(rule_runner, targets)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "1 file would be reformatted, 1 file would be left unchanged" in lint_results[0].stderr
    assert "1 file reformatted, 1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_respects_config_file(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [NEEDS_CONFIG_SOURCE])
    lint_results, fmt_result = run_black(
        rule_runner, [target], config="[tool.black]\nskip-string-normalization = 'true'\n"
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert "1 file would be left unchanged" in lint_results[0].stderr
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_digest(rule_runner, [NEEDS_CONFIG_SOURCE])
    assert fmt_result.did_change is False


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [NEEDS_CONFIG_SOURCE])
    lint_results, fmt_result = run_black(
        rule_runner, [target], passthrough_args="--skip-string-normalization"
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert "1 file would be left unchanged" in lint_results[0].stderr
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_digest(rule_runner, [NEEDS_CONFIG_SOURCE])
    assert fmt_result.did_change is False


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results, fmt_result = run_black(rule_runner, [target], skip=True)
    assert not lint_results
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False


@skip_unless_python38_present
def test_works_with_python38(rule_runner: RuleRunner) -> None:
    """Black's typed-ast dependency does not understand Python 3.8, so we must instead run Black
    with Python 3.8 when relevant."""
    py38_sources = FileContent(
        "py38.py",
        dedent(
            """\
            import datetime

            x = True
            if y := x:
                print("x is truthy and now assigned to y")


            class Foo:
                pass
            """
        ).encode(),
    )
    target = make_target(rule_runner, [py38_sources], interpreter_constraints=">=3.8")
    lint_results, fmt_result = run_black(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert "1 file would be left unchanged" in lint_results[0].stderr
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_digest(rule_runner, [py38_sources])
    assert fmt_result.did_change is False
