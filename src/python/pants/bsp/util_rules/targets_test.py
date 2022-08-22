# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.backend.java import target_types
from pants.backend.java.bsp import rules as java_bsp_rules
from pants.backend.java.compile import javac
from pants.backend.java.target_types import JavaSourceTarget
from pants.bsp.rules import rules as bsp_rules
from pants.bsp.spec.base import BuildTargetIdentifier
from pants.bsp.util_rules.targets import BSPBuildTargets, BSPTargetDefinition
from pants.engine.internals.parametrize import Parametrize
from pants.engine.rules import QueryRule
from pants.engine.target import Targets
from pants.jvm import jdk_rules
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.resolve import jvm_tool
from pants.jvm.strip_jar import strip_jar
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *bsp_rules(),
            *java_bsp_rules.rules(),
            *strip_jar.rules(),
            *javac.rules(),
            *jvm_tool.rules(),
            *jvm_util_rules.rules(),
            *jdk_rules.rules(),
            *target_types.rules(),
            QueryRule(BSPBuildTargets, ()),
            QueryRule(Targets, [BuildTargetIdentifier]),
        ],
        target_types=[JavaSourceTarget],
        objects={"parametrize": Parametrize},
    )


def test_config_file_parsing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "first.toml": textwrap.dedent(
                """\
            [groups.foo]
            display_name = "Foo"
            base_directory = "src/jvm"
            addresses = ["src/jvm::"]
            resolve = "jvm:jvm-default"
            """
            ),
            "second.toml": textwrap.dedent(
                """\
            [groups.foo]
            display_name = "Foo for My Team"
            base_directory = "src/jvm"
            addresses = ["src/jvm::", "my-team/src/jvm::"]
            resolve = "jvm:jvm-default"

            [groups.bar]
            display_name = "Bar"
            base_directory = "bar/src/jvm"
            addresses = ["bar/src/jvm::"]
            resolve = "jvm:bar"
            """
            ),
        }
    )
    rule_runner.set_options(
        ["--experimental-bsp-groups-config-files=['first.toml', 'second.toml']"]
    )

    bsp_build_targets = rule_runner.request(BSPBuildTargets, ())

    definitions = {
        (name, btgt.definition) for name, btgt in bsp_build_targets.targets_mapping.items()
    }
    assert definitions == {
        (
            "foo",
            BSPTargetDefinition(
                display_name="Foo for My Team",
                base_directory="src/jvm",
                addresses=("src/jvm::", "my-team/src/jvm::"),
                resolve_filter="jvm:jvm-default",
            ),
        ),
        (
            "bar",
            BSPTargetDefinition(
                display_name="Bar",
                base_directory="bar/src/jvm",
                addresses=("bar/src/jvm::",),
                resolve_filter="jvm:bar",
            ),
        ),
    }


def test_resolve_filtering(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "lib/Example1.java": "",
            "lib/Example2.java": "",
            "lib/BUILD": textwrap.dedent(
                """\
                java_source(name='lib1', source='Example1.java')

                java_source(
                    name='lib2',
                    source='Example2.java',
                    resolve=parametrize('jvm-default', 'other')
                )
                """
            ),
            "bsp.toml": textwrap.dedent(
                """\
                [groups.lib_jvm_default]
                base_directory = "lib"
                addresses = ["lib::"]
                resolve = "jvm:jvm-default"

                [groups.lib_other]
                base_directory = "lib"
                addresses = ["lib::"]
                resolve = "jvm:other"
                """
            ),
        }
    )
    rule_runner.set_options(
        [
            "--experimental-bsp-groups-config-files=['bsp.toml']",
            "--jvm-resolves={'jvm-default': 'unused', 'other': 'unused'}",
        ]
    )

    targets = rule_runner.request(Targets, [BuildTargetIdentifier("pants:lib_jvm_default")])
    assert {"lib:lib1", "lib:lib2@resolve=jvm-default"} == {str(t.address) for t in targets}

    targets = rule_runner.request(Targets, [BuildTargetIdentifier("pants:lib_other")])
    assert {"lib:lib2@resolve=other"} == {str(t.address) for t in targets}
