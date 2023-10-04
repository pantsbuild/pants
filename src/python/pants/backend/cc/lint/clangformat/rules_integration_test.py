# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.cc.lint.clangformat import skip_field
from pants.backend.cc.lint.clangformat.rules import ClangFormatFmtFieldSet, ClangFormatRequest
from pants.backend.cc.lint.clangformat.rules import rules as clangformat_rules
from pants.backend.cc.target_types import CCSourcesGeneratorTarget
from pants.backend.python import target_types_rules
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *clangformat_rules(),
            *skip_field.rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(FmtResult, (ClangFormatRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[CCSourcesGeneratorTarget],
    )


CLANG_FORMAT_FILE = dedent(
    """\
    ---
    BasedOnStyle: Mozilla
    """
)

UNFORMATTED_FILE = dedent(
    """\
    #include <iostream>

    int main() {
        std::cout << "Hello, world!" << std::endl;
        }
    """
)

DEFAULT_FORMATTED_FILE = dedent(
    """\
    #include <iostream>

    int main()
    {
        std::cout << "Hello, world!" << std::endl;
    }
    """
)

MOZILLA_FORMATTED_FILE = dedent(
    """\
    #include <iostream>

    int
    main()
    {
      std::cout << "Hello, world!" << std::endl;
    }
    """
)


def run_clangformat(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.cc.lint.clangformat", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    field_sets = [ClangFormatFmtFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            ClangFormatRequest.Batch(
                "",
                input_sources.snapshot.files,
                partition_metadata=None,
                snapshot=input_sources.snapshot,
            ),
        ],
    )
    return fmt_result


def test_success_on_formatted_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"main.cpp": DEFAULT_FORMATTED_FILE, "BUILD": "cc_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="main.cpp"))
    fmt_result = run_clangformat(
        rule_runner,
        [tgt],
    )
    assert fmt_result.output == rule_runner.make_snapshot({"main.cpp": DEFAULT_FORMATTED_FILE})
    assert fmt_result.did_change is False


def test_success_on_unformatted_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"main.cpp": UNFORMATTED_FILE, "BUILD": "cc_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="main.cpp"))
    fmt_result = run_clangformat(
        rule_runner,
        [tgt],
    )
    assert fmt_result.output == rule_runner.make_snapshot({"main.cpp": DEFAULT_FORMATTED_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.cpp": DEFAULT_FORMATTED_FILE,
            "bad.cpp": UNFORMATTED_FILE,
            "BUILD": "cc_sources(name='t')",
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.cpp")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.cpp")),
    ]
    fmt_result = run_clangformat(rule_runner, tgts)
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.cpp": DEFAULT_FORMATTED_FILE, "bad.cpp": DEFAULT_FORMATTED_FILE}
    )
    assert fmt_result.did_change is True


def test_config(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "main.cpp": UNFORMATTED_FILE,
            ".clang-format": CLANG_FORMAT_FILE,
            "BUILD": "cc_sources(name='t')",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="main.cpp"))
    fmt_result = run_clangformat(
        rule_runner,
        [tgt],
    )
    assert fmt_result.output == rule_runner.make_snapshot({"main.cpp": MOZILLA_FORMATTED_FILE})
    assert fmt_result.did_change is True
