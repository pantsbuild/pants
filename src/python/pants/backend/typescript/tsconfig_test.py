# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json

import pytest

from pants.backend.typescript import tsconfig
from pants.backend.typescript.target_types import TypeScriptSourceTarget
from pants.backend.typescript.tsconfig import (
    AllTSConfigs,
    TSConfig,
    TSConfigsRequest,
    _clean_tsconfig_contents,
)
from pants.core.target_types import TargetGeneratorSourcesHelperTarget
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[*tsconfig.rules(), QueryRule(AllTSConfigs, (TSConfigsRequest,))],
        target_types=[TypeScriptSourceTarget, TargetGeneratorSourcesHelperTarget],
    )


def test_parses_tsconfig(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "project/BUILD": "typescript_source()",
            "project/index.ts": "",
            "project/tsconfig.json": "{}",
        }
    )
    [ts_config] = rule_runner.request(AllTSConfigs, [TSConfigsRequest("tsconfig.json")])
    assert ts_config == TSConfig("project/tsconfig.json")


def test_parses_extended_tsconfig(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "project/BUILD": "typescript_source()",
            "project/index.ts": "",
            "project/tsconfig.json": json.dumps({"compilerOptions": {"baseUrl": "./"}}),
            "project/lib/tsconfig.json": json.dumps({"extends": ".."}),
        }
    )
    configs = rule_runner.request(AllTSConfigs, [TSConfigsRequest("tsconfig.json")])
    assert set(configs) == {
        TSConfig("project/tsconfig.json", base_url="./"),
        TSConfig("project/lib/tsconfig.json", base_url="./"),
    }


def test_parses_tsconfig_with_missing_extends_parent(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "project/BUILD": "typescript_source()",
            "project/index.ts": "",
            "project/lib/tsconfig.json": json.dumps({"extends": ".."}),
        }
    )
    configs = rule_runner.request(AllTSConfigs, [TSConfigsRequest("tsconfig.json")])
    assert set(configs) == {TSConfig("project/lib/tsconfig.json")}


def test_parses_extended_tsconfig_with_overrides(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "project/BUILD": "typescript_source()",
            "project/index.ts": "",
            "project/tsconfig.json": json.dumps({"compilerOptions": {"baseUrl": "./"}}),
            "project/lib/tsconfig.json": json.dumps(
                {"compilerOptions": {"baseUrl": "./src"}, "extends": ".."}
            ),
        }
    )
    configs = rule_runner.request(AllTSConfigs, [TSConfigsRequest("tsconfig.json")])
    assert set(configs) == {
        TSConfig("project/tsconfig.json", base_url="./"),
        TSConfig("project/lib/tsconfig.json", base_url="./src"),
    }


def test_parses_tsconfig_non_json_standard() -> None:
    # standard JSON
    content = """
    {"data": "foo"}
    """
    assert json.loads(_clean_tsconfig_contents(content)) == json.loads(content)

    # strings with internal escaping, e.g. "\"" or '\'' or even "\"//".
    content = """{ "data1": "fo\\"o", "data2": "fo\'o", "data3": "fo\\"//o" }"""
    assert json.loads(_clean_tsconfig_contents(content)) == json.loads(
        """{ "data1": "fo\\"o", "data2": "fo\'o", "data3": "fo\\"//o" }"""
    )

    # comments with internal "strings"
    content = """
    // testing "quotes"
    // and also "over
    // multiple lines"
    {"data": "foo"}
    /* or this "way
       over multiple" lines */
    """
    assert json.loads(_clean_tsconfig_contents(content)) == json.loads("""{"data": "foo"}""")

    # single-line comment
    content = """
    // comment here
    { // comment here
        "data": "foo" // comment here
    } // comment here
    //// comment here
    """
    assert json.loads(_clean_tsconfig_contents(content)) == json.loads("""{"data": "foo"}""")

    # multi-line comment
    content = """
    /*
    * first line comment here
    * second line comment here
    */
    {"data": "foo"} // single comment
    /**
    * first line comment here
    * second line comment here
    **/
    """
    assert json.loads(_clean_tsconfig_contents(content)) == json.loads("""{"data": "foo"}""")

    # single and multi-line comments interaction
    content = """
        /** abc /* looking like a nested comment block that is not /* **/
        /* abc /* looking like a nested comment block that is not /* */
        {"data": // /*
         "foo*/"
        }
        /* abc /* looking like a nested comment block that is not */
    """
    assert json.loads(_clean_tsconfig_contents(content)) == json.loads("""{"data": "foo*/"}""")

    # multi-line comment /*...*/ with nested single-line comments
    content = """
    /*
    * first line comment here
    * // single comment
    * second line comment here
    */
    {"data": "foo"} // single comment
    /**
    * first line comment here
    * second line comment here
    * // single comment
    **/
    """
    assert json.loads(_clean_tsconfig_contents(content)) == json.loads("""{"data": "foo"}""")

    # string literals with comment characters (such as URLs) are left untouched
    content = """
    // comment here
    {"baseUrl": "http://foo/bar/baz"} // comment here
    //// comment here
    """
    assert json.loads(_clean_tsconfig_contents(content)) == json.loads(
        """{"baseUrl": "http://foo/bar/baz"}"""
    )

    # trailing comma
    content = """
    // comment here
    {
        "baseUrl": [
            "http://foo/bar/baz",
        ],
        "data": "foo",
    } // comment here
    //// comment here
    """
    assert json.loads(_clean_tsconfig_contents(content)) == json.loads(
        """{"baseUrl": ["http://foo/bar/baz"], "data": "foo"}"""
    )

    # strings that look like they contain a trailing comma
    content = """{
        "data1": "foo,",
        "data2": "foo,}",
        "data3": "foo,]"
        } """
    assert json.loads(_clean_tsconfig_contents(content)) == json.loads(content)


def test_validate_tsconfig_outdir_missing() -> None:
    ts_config = TSConfig(path="project/tsconfig.json", out_dir=None)

    with pytest.raises(ValueError) as exc_info:
        ts_config.validate_outdir()

    error_message = str(exc_info.value)
    assert "missing required 'outDir' setting" in error_message


def test_validate_tsconfig_outdir_with_parent_references() -> None:
    ts_config = TSConfig(path="project/tsconfig.json", out_dir="../dist")

    with pytest.raises(ValueError) as exc_info:
        ts_config.validate_outdir()

    error_message = str(exc_info.value)
    assert "uses '..' path components" in error_message

    # Test with multiple .. components
    ts_config = TSConfig(path="project/tsconfig.json", out_dir="../../build")

    with pytest.raises(ValueError) as exc_info:
        ts_config.validate_outdir()

    error_message = str(exc_info.value)
    assert "uses '..' path components" in error_message

    # Test with .. in the middle of the path
    ts_config = TSConfig(path="project/tsconfig.json", out_dir="./lib/../dist")

    with pytest.raises(ValueError) as exc_info:
        ts_config.validate_outdir()

    error_message = str(exc_info.value)
    assert "uses '..' path components" in error_message


def test_validate_tsconfig_outdir_with_absolute_paths() -> None:
    ts_config = TSConfig(path="project/tsconfig.json", out_dir="/tmp/build")

    with pytest.raises(ValueError) as exc_info:
        ts_config.validate_outdir()

    error_message = str(exc_info.value)
    assert "absolute outDir" in error_message


def test_validate_tsconfig_outdir_valid() -> None:
    valid_configs = [
        TSConfig(path="project/tsconfig.json", out_dir="./dist"),
        TSConfig(path="project/tsconfig.json", out_dir="dist"),
        TSConfig(path="project/tsconfig.json", out_dir="./build"),
        TSConfig(path="project/tsconfig.json", out_dir="./lib/output"),
        TSConfig(path="project/tsconfig.json", out_dir="build/js"),
    ]

    for ts_config in valid_configs:
        ts_config.validate_outdir()
