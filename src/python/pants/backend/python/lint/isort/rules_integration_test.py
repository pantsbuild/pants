# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Sequence, Tuple

import pytest

from pants.backend.python.lint.isort.rules import IsortFieldSet, IsortRequest
from pants.backend.python.lint.isort.rules import rules as isort_rules
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
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *isort_rules(),
            QueryRule(LintResults, (IsortRequest, OptionsBootstrapper, PantsEnvironment)),
            QueryRule(FmtResult, (IsortRequest, OptionsBootstrapper, PantsEnvironment)),
            QueryRule(SourceFiles, (SourceFilesRequest, OptionsBootstrapper, PantsEnvironment)),
        ]
    )


GOOD_SOURCE = FileContent(path="good.py", content=b"from animals import cat, dog\n")
BAD_SOURCE = FileContent(path="bad.py", content=b"from colors import green, blue\n")
FIXED_BAD_SOURCE = FileContent(path="bad.py", content=b"from colors import blue, green\n")
# Note the as import. Isort by default keeps as imports on a new line, so this wouldn't be
# reformatted by default. If we set the config/CLI args correctly, isort will combine the two
# imports into one line.
NEEDS_CONFIG_SOURCE = FileContent(
    path="needs_config.py",
    content=b"from colors import blue\nfrom colors import green as verde\n",
)
FIXED_NEEDS_CONFIG_SOURCE = FileContent(
    path="needs_config.py", content=b"from colors import blue, green as verde\n"
)


def make_target_with_origin(rule_runner: RuleRunner, source_files: List[FileContent]) -> Target:
    for source_file in source_files:
        rule_runner.create_file(f"{source_file.path}", source_file.content.decode())
    return PythonLibrary({}, address=Address.parse(":target"))


def run_isort(
    rule_runner: RuleRunner,
    targets: List[Target],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[str] = None,
    skip: bool = False,
) -> Tuple[Sequence[LintResult], FmtResult]:
    args = ["--backend-packages=pants.backend.python.lint.isort"]
    if config is not None:
        rule_runner.create_file(relpath=".isort.cfg", contents=config)
        args.append("--isort-config=.isort.cfg")
    if passthrough_args:
        args.append(f"--isort-args='{passthrough_args}'")
    if skip:
        args.append("--isort-skip")
    options_bootstrapper = create_options_bootstrapper(args=args)
    field_sets = [IsortFieldSet.create(tgt) for tgt in targets]
    pants_env = PantsEnvironment()
    lint_results = rule_runner.request(
        LintResults, [IsortRequest(field_sets), options_bootstrapper, pants_env]
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
            IsortRequest(field_sets, prior_formatter_result=input_sources.snapshot),
            options_bootstrapper,
            pants_env,
        ],
    )
    return lint_results.results, fmt_result


def get_digest(rule_runner: RuleRunner, source_files: List[FileContent]) -> Digest:
    return rule_runner.request(Digest, [CreateDigest(source_files)])


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target_with_origin(rule_runner, [GOOD_SOURCE])
    lint_results, fmt_result = run_isort(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE])
    assert fmt_result.did_change is False


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target_with_origin(rule_runner, [BAD_SOURCE])
    lint_results, fmt_result = run_isort(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.py Imports are incorrectly sorted" in lint_results[0].stderr
    assert fmt_result.stdout == "Fixing bad.py\n"
    assert fmt_result.output == get_digest(rule_runner, [FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target_with_origin(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    lint_results, fmt_result = run_isort(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.py Imports are incorrectly sorted" in lint_results[0].stderr
    assert "good.py" not in lint_results[0].stderr
    assert fmt_result.stdout == "Fixing bad.py\n"
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    targets = [
        make_target_with_origin(rule_runner, [GOOD_SOURCE]),
        make_target_with_origin(rule_runner, [BAD_SOURCE]),
    ]
    lint_results, fmt_result = run_isort(rule_runner, targets)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.py Imports are incorrectly sorted" in lint_results[0].stderr
    assert "good.py" not in lint_results[0].stderr
    assert "Fixing bad.py\n" == fmt_result.stdout
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_respects_config_file(rule_runner: RuleRunner) -> None:
    target = make_target_with_origin(rule_runner, [NEEDS_CONFIG_SOURCE])
    lint_results, fmt_result = run_isort(
        rule_runner, [target], config="[settings]\ncombine_as_imports=True\n"
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "config.py Imports are incorrectly sorted" in lint_results[0].stderr
    assert fmt_result.stdout == "Fixing needs_config.py\n"
    assert fmt_result.output == get_digest(rule_runner, [FIXED_NEEDS_CONFIG_SOURCE])
    assert fmt_result.did_change is True


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    target = make_target_with_origin(rule_runner, [NEEDS_CONFIG_SOURCE])
    lint_results, fmt_result = run_isort(rule_runner, [target], passthrough_args="--combine-as")
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "config.py Imports are incorrectly sorted" in lint_results[0].stderr
    assert fmt_result.stdout == "Fixing needs_config.py\n"
    assert fmt_result.output == get_digest(rule_runner, [FIXED_NEEDS_CONFIG_SOURCE])
    assert fmt_result.did_change is True


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target_with_origin(rule_runner, [BAD_SOURCE])
    lint_results, fmt_result = run_isort(rule_runner, [target], skip=True)
    assert not lint_results
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False
