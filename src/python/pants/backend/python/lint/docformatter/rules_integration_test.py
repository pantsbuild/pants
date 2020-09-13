# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Sequence, Tuple

import pytest

from pants.backend.python.lint.docformatter.rules import DocformatterFieldSet, DocformatterRequest
from pants.backend.python.lint.docformatter.rules import rules as docformatter_rules
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
            *docformatter_rules(),
            QueryRule(LintResults, (DocformatterRequest, OptionsBootstrapper, PantsEnvironment)),
            QueryRule(FmtResult, (DocformatterRequest, OptionsBootstrapper, PantsEnvironment)),
            QueryRule(SourceFiles, (SourceFilesRequest, OptionsBootstrapper, PantsEnvironment)),
        ]
    )


GOOD_SOURCE = FileContent(path="good.py", content=b'"""Good docstring."""\n')
BAD_SOURCE = FileContent(path="bad.py", content=b'"""Oops, missing a period"""\n')
FIXED_BAD_SOURCE = FileContent(path="bad.py", content=b'"""Oops, missing a period."""\n')


def make_target(rule_runner: RuleRunner, source_files: List[FileContent]) -> Target:
    for source_file in source_files:
        rule_runner.create_file(f"{source_file.path}", source_file.content.decode())
    return PythonLibrary({}, address=Address.parse(":target"))


def run_docformatter(
    rule_runner: RuleRunner,
    targets: List[Target],
    *,
    passthrough_args: Optional[str] = None,
    skip: bool = False,
) -> Tuple[Sequence[LintResult], FmtResult]:
    args = ["--backend-packages=pants.backend.python.lint.docformatter"]
    if passthrough_args:
        args.append(f"--docformatter-args='{passthrough_args}'")
    if skip:
        args.append("--docformatter-skip")
    options_bootstrapper = create_options_bootstrapper(args=args)
    field_sets = [DocformatterFieldSet.create(tgt) for tgt in targets]
    pants_env = PantsEnvironment()
    lint_results = rule_runner.request_product(
        LintResults, [DocformatterRequest(field_sets), options_bootstrapper, pants_env]
    )
    input_sources = rule_runner.request_product(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
            options_bootstrapper,
            pants_env,
        ],
    )
    fmt_result = rule_runner.request_product(
        FmtResult,
        [
            DocformatterRequest(field_sets, prior_formatter_result=input_sources.snapshot),
            options_bootstrapper,
            pants_env,
        ],
    )
    return lint_results.results, fmt_result


def get_digest(rule_runner: RuleRunner, source_files: List[FileContent]) -> Digest:
    return rule_runner.request_product(Digest, [CreateDigest(source_files)])


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    lint_results, fmt_result = run_docformatter(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE])
    assert fmt_result.did_change is False


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results, fmt_result = run_docformatter(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 3
    assert lint_results[0].stderr.strip() == BAD_SOURCE.path
    assert fmt_result.output == get_digest(rule_runner, [FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    lint_results, fmt_result = run_docformatter(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 3
    assert lint_results[0].stderr.strip() == BAD_SOURCE.path
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    targets = [
        make_target(rule_runner, [GOOD_SOURCE]),
        make_target(rule_runner, [BAD_SOURCE]),
    ]
    lint_results, fmt_result = run_docformatter(rule_runner, targets)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 3
    assert lint_results[0].stderr.strip() == BAD_SOURCE.path
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    needs_config = FileContent(
        path="needs_config.py",
        content=b'"""\nOne line docstring acting like it\'s multiline.\n"""\n',
    )
    target = make_target(rule_runner, [needs_config])
    lint_results, fmt_result = run_docformatter(
        rule_runner, [target], passthrough_args="--make-summary-multi-line"
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""
    assert fmt_result.output == get_digest(rule_runner, [needs_config])
    assert fmt_result.did_change is False


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results, fmt_result = run_docformatter(rule_runner, [target], skip=True)
    assert not lint_results
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False
