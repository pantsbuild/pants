# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

import pytest

from pants.backend.python.lint.black.rules import rules as black_rules
from pants.backend.python.lint.isort.rules import rules as isort_rules
from pants.backend.python.lint.python_fmt import PythonFmtTargets, format_python_target
from pants.backend.python.target_types import PythonLibrary
from pants.core.goals.fmt import LanguageFmtResults
from pants.core.util_rules.pants_environment import PantsEnvironment
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.target import Targets
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            format_python_target,
            *black_rules(),
            *isort_rules(),
            QueryRule(
                LanguageFmtResults, (PythonFmtTargets, OptionsBootstrapper, PantsEnvironment)
            ),
        ]
    )


def run_black_and_isort(
    rule_runner: RuleRunner,
    source_files: List[FileContent],
    *,
    name: str,
    extra_args: Optional[List[str]] = None,
) -> LanguageFmtResults:
    for source_file in source_files:
        rule_runner.create_file(source_file.path, source_file.content.decode())
    targets = PythonFmtTargets(Targets([PythonLibrary({}, address=Address.parse(f"test:{name}"))]))
    args = [
        "--backend-packages=['pants.backend.python.lint.black', 'pants.backend.python.lint.isort']",
        *(extra_args or []),
    ]
    results = rule_runner.request(
        LanguageFmtResults, [targets, create_options_bootstrapper(args=args), PantsEnvironment()]
    )
    return results


def get_digest(rule_runner: RuleRunner, source_files: List[FileContent]) -> Digest:
    return rule_runner.request(Digest, [CreateDigest(source_files)])


def test_multiple_formatters_changing_the_same_file(rule_runner: RuleRunner) -> None:
    original_source = FileContent(
        "test/target.py",
        content=b"from animals import dog, cat\n\nprint('hello')\n",
    )
    fixed_source = FileContent(
        "test/target.py",
        content=b'from animals import cat, dog\n\nprint("hello")\n',
    )
    results = run_black_and_isort(rule_runner, [original_source], name="same_file")
    assert results.output == get_digest(rule_runner, [fixed_source])
    assert results.did_change is True


def test_multiple_formatters_changing_different_files(rule_runner: RuleRunner) -> None:
    original_sources = [
        FileContent("test/isort.py", content=b"from animals import dog, cat\n"),
        FileContent("test/black.py", content=b"print('hello')\n"),
    ]
    fixed_sources = [
        FileContent("test/isort.py", content=b"from animals import cat, dog\n"),
        FileContent("test/black.py", content=b'print("hello")\n'),
    ]
    results = run_black_and_isort(rule_runner, original_sources, name="different_file")
    assert results.output == get_digest(rule_runner, fixed_sources)
    assert results.did_change is True


def test_skipped_formatter(rule_runner: RuleRunner) -> None:
    """Ensure that a skipped formatter does not interfere with other formatters."""
    original_source = FileContent(
        "test/skipped.py",
        content=b"from animals import dog, cat\n\nprint('hello')\n",
    )
    fixed_source = FileContent(
        "test/skipped.py",
        content=b"from animals import cat, dog\n\nprint('hello')\n",
    )
    results = run_black_and_isort(
        rule_runner, [original_source], name="skipped", extra_args=["--black-skip"]
    )
    assert results.output == get_digest(rule_runner, [fixed_source])
    assert results.did_change is True


def test_no_changes(rule_runner: RuleRunner) -> None:
    source = FileContent(
        "test/target.py",
        content=b'from animals import cat, dog\n\nprint("hello")\n',
    )
    results = run_black_and_isort(rule_runner, [source], name="different_file")
    assert results.output == get_digest(rule_runner, [source])
    assert results.did_change is False
