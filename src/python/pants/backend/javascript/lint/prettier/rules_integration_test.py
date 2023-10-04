# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.javascript.lint.prettier import rules as prettier_rules
from pants.backend.javascript.lint.prettier import skip_field
from pants.backend.javascript.lint.prettier.rules import PrettierFmtFieldSet, PrettierFmtRequest
from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget
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
            *prettier_rules.rules(),
            *nodejs.rules(),
            *skip_field.rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(FmtResult, (PrettierFmtRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[JSSourcesGeneratorTarget],
    )


PRETTIERRC_FILE = dedent(
    """\
    {
        "tabWidth": 4
    }
    """
)


UNFORMATTED_FILE = dedent(
    """\
    function greet() {
    console.log("Hello, world!");
    }

    greet();
    """
)

DEFAULT_FORMATTED_FILE = dedent(
    """\
    function greet() {
      console.log("Hello, world!");
    }

    greet();
    """
)

CONFIG_FORMATTED_FILE = dedent(
    """\
    function greet() {
        console.log("Hello, world!");
    }

    greet();
    """
)


def run_prettier(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> FmtResult:
    rule_runner.set_options(
        [
            "--backend-packages=['pants.backend.javascript', 'pants.backend.javascript.lint.prettier']",
            *(extra_args or ()),
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    field_sets = [PrettierFmtFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            PrettierFmtRequest.Batch(
                "",
                input_sources.snapshot.files,
                partition_metadata=None,
                snapshot=input_sources.snapshot,
            ),
        ],
    )
    return fmt_result


def test_success_on_formatted_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"main.js": DEFAULT_FORMATTED_FILE, "BUILD": "javascript_sources(name='t')"}
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="main.js"))
    fmt_result = run_prettier(
        rule_runner,
        [tgt],
    )
    assert fmt_result.output == rule_runner.make_snapshot({"main.js": DEFAULT_FORMATTED_FILE})
    assert fmt_result.did_change is False


def test_success_on_unformatted_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"main.js": UNFORMATTED_FILE, "BUILD": "javascript_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="main.js"))
    fmt_result = run_prettier(
        rule_runner,
        [tgt],
    )
    assert fmt_result.output == rule_runner.make_snapshot({"main.js": DEFAULT_FORMATTED_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.js": DEFAULT_FORMATTED_FILE,
            "bad.js": UNFORMATTED_FILE,
            "BUILD": "javascript_sources(name='t')",
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.js")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.js")),
    ]
    fmt_result = run_prettier(rule_runner, tgts)
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.js": DEFAULT_FORMATTED_FILE, "bad.js": DEFAULT_FORMATTED_FILE}
    )
    assert fmt_result.did_change is True


def test_config(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "main.js": UNFORMATTED_FILE,
            ".prettierrc": PRETTIERRC_FILE,
            "BUILD": "javascript_sources(name='t')",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="main.js"))
    fmt_result = run_prettier(
        rule_runner,
        [tgt],
    )
    assert fmt_result.output == rule_runner.make_snapshot({"main.js": CONFIG_FORMATTED_FILE})
    assert fmt_result.did_change is True
