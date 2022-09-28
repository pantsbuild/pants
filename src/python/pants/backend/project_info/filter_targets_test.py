# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from textwrap import dedent

import pytest

from pants.backend.project_info import filter_targets, list_targets
from pants.backend.project_info.filter_targets import FilterGoal, TargetGranularity
from pants.backend.project_info.list_targets import List
from pants.engine.rules import rule
from pants.engine.target import (
    GeneratedTargets,
    GenerateTargetsRequest,
    MultipleSourcesField,
    SingleSourceField,
    Tags,
    Target,
    TargetFilesGenerator,
    TargetGenerator,
    UnrecognizedTargetTypeException,
)
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner, engine_error


class MockTarget(Target):
    alias = "tgt"
    core_fields = (Tags,)
    deprecated_alias = "deprecated_tgt"
    deprecated_alias_removal_version = "99.9.0.dev0"


class MockSingleSourceField(SingleSourceField):
    pass


class MockGeneratedFileTarget(Target):
    alias = "file_generated"
    core_fields = (MockSingleSourceField, Tags)


class MockMultipleSourcesField(MultipleSourcesField):
    pass


class MockFileTargetGenerator(TargetFilesGenerator):
    alias = "file_generator"
    generated_target_cls = MockGeneratedFileTarget
    core_fields = (MockMultipleSourcesField, Tags)
    copied_fields = (Tags,)
    moved_fields = ()


class MockGeneratedNonfileTarget(Target):
    alias = "nonfile_generated"
    core_fields = (Tags,)


class MockNonfileTargetGenerator(TargetGenerator):
    alias = "nonfile_generator"
    core_fields = (Tags,)
    copied_fields = (Tags,)
    moved_fields = ()


class MockGenerateTargetsRequest(GenerateTargetsRequest):
    generate_from = MockNonfileTargetGenerator


@rule
async def generate_mock_generated_target(request: MockGenerateTargetsRequest) -> GeneratedTargets:
    return GeneratedTargets(
        request.generator,
        [
            MockGeneratedNonfileTarget(
                request.template, request.generator.address.create_generated("gen")
            )
        ],
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *filter_targets.rules(),
            *list_targets.rules(),
            generate_mock_generated_target,
            UnionRule(GenerateTargetsRequest, MockGenerateTargetsRequest),
        ],
        target_types=[MockTarget, MockFileTargetGenerator, MockNonfileTargetGenerator],
    )


def assert_targets(
    rule_runner: RuleRunner,
    expected: set[str],
    *,
    target_type: list[str] | None = None,
    address_regex: list[str] | None = None,
    tag_regex: list[str] | None = None,
    granularity: TargetGranularity = TargetGranularity.all_targets,
) -> None:
    filter_result = rule_runner.run_goal_rule(
        FilterGoal,
        args=[
            f"--target-type={target_type or []}",
            f"--address-regex={address_regex or []}",
            f"--tag-regex={tag_regex or []}",
            f"--granularity={granularity.value}",
            "::",
        ],
    )
    assert set(filter_result.stdout.splitlines()) == expected

    list_result = rule_runner.run_goal_rule(
        List,
        global_args=[
            f"--filter-target-type={target_type or []}",
            f"--filter-address-regex={address_regex or []}",
            f"--filter-tag-regex={tag_regex or []}",
            f"--filter-granularity={granularity.value}",
            "::",
        ],
    )
    assert set(list_result.stdout.splitlines()) == expected


def test_no_filters_provided(rule_runner: RuleRunner) -> None:
    """When no filters, list all targets, like the `list` the goal.

    Include target generators and generated targets.
    """
    rule_runner.write_files(
        {
            "f.txt": "",
            "BUILD": dedent(
                """\
                tgt(name="tgt")
                file_generator(name="file", sources=["f.txt"])
                nonfile_generator(name="nonfile")
                """
            ),
        }
    )
    assert_targets(
        rule_runner, {"//:tgt", "//:file", "//f.txt:file", "//:nonfile", "//:nonfile#gen"}
    )


def test_filter_by_target_type(rule_runner: RuleRunner, caplog) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                tgt(name="tgt")
                nonfile_generator(name="nonfile")
                """
            ),
        }
    )

    assert_targets(rule_runner, {"//:tgt"}, target_type=["tgt"])
    assert_targets(rule_runner, {"//:nonfile"}, target_type=["+nonfile_generator"])
    assert_targets(rule_runner, {"//:tgt", "//:nonfile#gen"}, target_type=["-nonfile_generator"])
    # The comma is inside the string, so these are ORed.
    assert_targets(rule_runner, {"//:tgt", "//:nonfile"}, target_type=["tgt,nonfile_generator"])
    # A target can only have one type, so this output should be empty.
    assert_targets(rule_runner, set(), target_type=["tgt", "nonfile_generator"])

    # Deprecated aliases works too.
    caplog.clear()
    assert_targets(rule_runner, {"//:tgt"}, target_type=["deprecated_tgt"])
    assert caplog.records
    assert "`--filter-target-type=deprecated_tgt`" in caplog.text

    with engine_error(UnrecognizedTargetTypeException):
        assert_targets(rule_runner, set(), target_type=["invalid"])


def test_filter_by_address_regex(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "dir1/BUILD": "tgt(name='lib')",
            "dir2/BUILD": "tgt(name='lib')",
            "common/BUILD": "tgt(name='tests')",
        }
    )
    assert_targets(rule_runner, {"dir1:lib", "dir2:lib"}, address_regex=[r"^dir"])
    assert_targets(rule_runner, {"dir1:lib"}, address_regex=[r"+dir1:lib$"])
    assert_targets(rule_runner, {"common:tests"}, address_regex=["-dir"])
    # The comma ORs the regex.
    assert_targets(rule_runner, {"common:tests", "dir1:lib"}, address_regex=["dir1,common"])
    # This ANDs the regex.
    assert_targets(rule_runner, {"dir2:lib"}, address_regex=[r"^dir", "2:lib$"])

    # Invalid regex.
    with engine_error(re.error):
        assert_targets(rule_runner, set(), address_regex=["("])


def test_filter_by_tag_regex(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                tgt(name="no-tags")
                tgt(name="t1", tags=["tag1"])
                tgt(name="t2", tags=["tag2"])
                tgt(name="both", tags=["tag1", "tag2"])
                """
            ),
        }
    )
    assert_targets(rule_runner, {"//:both", "//:t2"}, tag_regex=[r"t.?g2$"])
    assert_targets(rule_runner, {"//:both", "//:t1"}, tag_regex=["+tag1"])
    assert_targets(rule_runner, {"//:no-tags"}, tag_regex=["-tag"])
    # The comma ORs the regex.
    assert_targets(rule_runner, {"//:both", "//:t1", "//:t2"}, tag_regex=[r"t.?g2$,tag1"])
    # This ANDs the regex.
    assert_targets(rule_runner, {"//:both"}, tag_regex=[r"t.?g2$", "tag1"])

    # Invalid regex.
    with engine_error(re.error):
        assert_targets(rule_runner, set(), tag_regex=["("])


def test_filter_by_granularity(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.txt": "",
            "BUILD": dedent(
                """\
                tgt(name="tgt")
                file_generator(name="file", sources=["f.txt"])
                nonfile_generator(name="nonfile")
                """
            ),
        }
    )
    file_targets = {"//f.txt:file"}
    build_targets = {"//:tgt", "//:file", "//:nonfile", "//:nonfile#gen"}
    assert_targets(
        rule_runner, {*file_targets, *build_targets}, granularity=TargetGranularity.all_targets
    )
    assert_targets(rule_runner, file_targets, granularity=TargetGranularity.file_targets)
    assert_targets(rule_runner, build_targets, granularity=TargetGranularity.build_targets)
