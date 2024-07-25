# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import (
    AllPackageJson,
    NodePackageTestScriptField,
    NodeTestScript,
    NodeThirdPartyPackageTarget,
    PackageJson,
    PackageJsonImports,
    PackageJsonSourceField,
    PackageJsonTarget,
)
from pants.build_graph.address import Address
from pants.core.target_types import TargetGeneratorSourcesHelperTarget
from pants.engine.fs import PathGlobs
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.engine.target import AllTargets
from pants.testutil.rule_runner import RuleRunner, engine_error
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *package_json.rules(),
            QueryRule(AllPackageJson, ()),
            QueryRule(Owners, (OwnersRequest,)),
            QueryRule(PackageJsonImports, (PackageJsonSourceField,)),
        ],
        target_types=[
            PackageJsonTarget,
            NodeThirdPartyPackageTarget,
            TargetGeneratorSourcesHelperTarget,
        ],
        objects=dict(package_json.build_file_aliases().objects),
    )


def given_package(name: str, version: str) -> str:
    return json.dumps({"name": name, "version": version})


def get_snapshots_for_package(rule_runner: RuleRunner, *package_path: str) -> Iterable[Snapshot]:
    return (rule_runner.request(Snapshot, [PathGlobs([path])]) for path in package_path)


def test_parses_package_jsons(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package("ham", "0.0.1"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    [foo_package_snapshot, bar_package_snapshot] = get_snapshots_for_package(
        rule_runner, "src/js/foo/package.json", "src/js/bar/package.json"
    )
    pkg_jsons = rule_runner.request(AllPackageJson, [])
    assert set(pkg_jsons) == {
        PackageJson(
            content=FrozenDict.deep_freeze(json.loads(given_package("ham", "0.0.1"))),
            name="ham",
            version="0.0.1",
            snapshot=foo_package_snapshot,
        ),
        PackageJson(
            content=FrozenDict.deep_freeze(json.loads(given_package("spam", "0.0.2"))),
            name="spam",
            version="0.0.2",
            snapshot=bar_package_snapshot,
        ),
    }


def test_parse_package_json_without_name(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            # No name in package.json, should cause an error.
            "src/js/package.json": json.dumps({"version": "0.0.1"}),
        }
    )
    with engine_error(ValueError, contains="No package name found in package.json"):
        rule_runner.request(AllPackageJson, [])


def test_generates_third_party_node_package_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": json.dumps(
                {"name": "ham", "version": "0.0.1", "dependencies": {"chalk": "^5.2.0"}}
            ),
        }
    )
    assert rule_runner.get_target(Address("src/js", generated_name="chalk"))


def test_does_not_generate_third_party_node_package_target_for_first_party_package_name(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/a/BUILD": "package_json()",
            "src/js/a/package.json": json.dumps(
                {"name": "ham", "version": "0.0.1", "dependencies": {"chalk": "^5.2.0"}}
            ),
            "src/js/b/BUILD": "package_json()",
            "src/js/b/package.json": json.dumps(
                {"name": "spam", "version": "0.0.1", "dependencies": {"ham": "0.0.1"}}
            ),
        }
    )
    addresses = sorted(str(tgt.address) for tgt in rule_runner.request(AllTargets, ()))
    assert "src/js/b#ham" not in addresses
    assert addresses == [
        "src/js/a#chalk",
        "src/js/a#ham",
        "src/js/a#src/js/a/package.json",
        "src/js/b#spam",
        "src/js/b#src/js/b/package.json",
    ]


def test_does_not_consider_package_json_without_a_target(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/a/BUILD": "package_json()",
            "src/js/a/package.json": json.dumps(
                {"name": "ham", "version": "0.0.1", "dependencies": {"chalk": "^5.2.0"}}
            ),
            "src/js/b/package.json": json.dumps(
                {"name": "spam", "version": "0.0.1", "dependencies": {"ham": "0.0.1"}}
            ),
        }
    )
    all_packages = rule_runner.request(AllPackageJson, ())
    assert len(all_packages) == 1
    assert all_packages[0].name == "ham"


def test_generates_build_script_targets(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(entry_point="build", output_directories=["www/"])
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {"name": "ham", "version": "0.0.1", "scripts": {"build": "parcel"}}
            ),
        }
    )
    addresses = sorted(str(tgt.address) for tgt in rule_runner.request(AllTargets, ()))
    assert addresses == ["src/js#build", "src/js#ham", "src/js#src/js/package.json"]


def test_generates_default_test_script_field(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(entry_point="build", output_directories=["www/"])
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {"name": "ham", "version": "0.0.1", "scripts": {"build": "parcel"}}
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    assert tgt[NodePackageTestScriptField].value == NodeTestScript()


def test_can_specify_custom_test_script_field(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(entry_point="build", output_directories=["www/"]),
                        node_test_script(entry_point="jest-test", coverage_args=["--coverage"]),
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "scripts": {"build": "parcel", "jest-test": "jest"},
                }
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    assert tgt[NodePackageTestScriptField].value == NodeTestScript(
        entry_point="jest-test", coverage_args=("--coverage",)
    )


def test_specifying_multiple_custom_test_scripts_is_an_error(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_test_script(entry_point="test1"),
                        node_test_script(entry_point="test2"),
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "scripts": {"test1": "jest", "test2": "mocha"},
                }
            ),
        }
    )
    with pytest.raises(ExecutionError):
        rule_runner.get_target(Address("src/js", generated_name="ham"))


def test_specifying_missing_custom_coverage_entry_point_script_is_an_error(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_test_script(entry_point="test", coverage_entry_point="test:coverage"),
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "scripts": {"test": "mocha", "test:cov": "nyc test"},
                }
            ),
        }
    )
    with pytest.raises(ExecutionError):
        rule_runner.get_target(Address("src/js", generated_name="ham"))


def test_parses_subpath_imports(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json()
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "imports": {
                        "#a": "./yep.js",
                        "#b": "some-package",
                        "#c": {"node": "polyfill", "default": "./polyfill.js"},
                        "#d/module/js/*.js": "./module/*.js",
                    },
                }
            ),
        }
    )

    tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    imports = rule_runner.request(PackageJsonImports, (tgt[PackageJsonSourceField],))

    assert imports.imports == FrozenDict(
        {
            "#a": ("./yep.js",),
            "#b": ("some-package",),
            "#c": (
                "./polyfill.js",
                "polyfill",
            ),
            "#d/module/js/*.js": ("./module/*.js",),
        }
    )
