# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.lint.black.rules import rules as black_rules
from pants.backend.python.lint.isort.rules import rules as isort_rules
from pants.backend.python.lint.python_fmt import PythonFmtTargets, format_python_target
from pants.backend.python.target_types import PythonLibrary
from pants.core.goals.fmt import LanguageFmtResults, enrich_fmt_result
from pants.core.util_rules import config_files, source_files
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.target import Target, Targets
from pants.testutil.rule_runner import QueryRule, RuleRunner

BAD_FILE = "from animals import dog, cat\n\nprint('hello')\n"
FIXED_BAD_FILE = 'from animals import cat, dog\n\nprint("hello")\n'


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            enrich_fmt_result,
            format_python_target,
            *black_rules(),
            *isort_rules(),
            *source_files.rules(),
            *config_files.rules(),
            QueryRule(LanguageFmtResults, (PythonFmtTargets,)),
        ],
        target_types=[PythonLibrary],
    )


def run_black_and_isort(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> LanguageFmtResults:
    fmt_targets = PythonFmtTargets(Targets(targets))
    rule_runner.set_options(
        [
            "--backend-packages=['pants.backend.python.lint.black', 'pants.backend.python.lint.isort']",
            *(extra_args or []),
        ],
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
    return rule_runner.request(LanguageFmtResults, [fmt_targets])


def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


def test_multiple_formatters_changing_the_same_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    results = run_black_and_isort(rule_runner, [tgt])
    assert results.output == get_digest(rule_runner, {"f.py": FIXED_BAD_FILE})
    assert results.did_change is True


def test_multiple_formatters_changing_different_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "isort.py": "from animals import dog, cat\n",
            "black.py": "print('hello')\n",
            "BUILD": "python_library(name='t')",
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="isort.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="black.py")),
    ]
    results = run_black_and_isort(rule_runner, tgts)
    assert results.output == get_digest(
        rule_runner,
        {"isort.py": "from animals import cat, dog\n", "black.py": 'print("hello")\n'},
    )
    assert results.did_change is True


def test_skipped_formatter(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    results = run_black_and_isort(rule_runner, [tgt], extra_args=["--black-skip"])
    assert results.output == get_digest(
        rule_runner, {"f.py": "from animals import cat, dog\n\nprint('hello')\n"}
    )
    assert results.did_change is True


def test_no_changes(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": FIXED_BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    results = run_black_and_isort(rule_runner, [tgt])
    assert results.output == get_digest(rule_runner, {"f.py": FIXED_BAD_FILE})
    assert results.did_change is False
