# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os

import pytest

from pants.base.specs import Specs
from pants.engine.addresses import Addresses
from pants.engine.internals.native_engine import Address
from pants.engine.internals.parametrize import Parametrize
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.engine.target import (
    AllTargets,
    InvalidFieldException,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    StringField,
    Tags,
    Target,
    TargetFilesGenerator,
)
from pants.testutil.rule_runner import RuleRunner


class MockSingleSourceField(SingleSourceField):
    pass


class MockMultipleSourcesField(MultipleSourcesField):
    pass


class PythonResolveField(StringField):
    alias = "python_resolve"
    required = False


class MockGeneratedTarget(Target):
    alias = "generated"
    core_fields = (
        # MockDependencies,
        Tags,
        MockSingleSourceField,
    )


class MockTargetGenerator(TargetFilesGenerator):
    alias = "generator"
    core_fields = (MockMultipleSourcesField, OverridesField)
    generated_target_cls = MockGeneratedTarget
    copied_fields = ()
    moved_fields = (Tags,)


def build_rule_runner(*plugin_registrations) -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(Addresses, [Specs]),
            QueryRule(AllTargets, []),
            *plugin_registrations,
        ],
        target_types=[MockTargetGenerator, MockGeneratedTarget],
        objects={"parametrize": Parametrize},
        # NB: The `graph` module masks the environment is most/all positions. We disable the
        # inherent environment so that the positions which do require the environment are
        # highlighted.
        inherent_environment=None,
    )


def assert_generated(
    rule_runner: RuleRunner,
    address: Address,
    build_content: str,
    files: list[str],
    expected_targets: set[Target] | None = None,
) -> None:
    rule_runner.write_files(
        {
            f"{address.spec_path}/BUILD": build_content,
            **{os.path.join(address.spec_path, f): "" for f in files},
        }
    )
    targets = rule_runner.request(AllTargets, [])
    if expected_targets:
        assert expected_targets == set(targets)


def test_generate_target_with_a_plugin_field() -> None:
    rule_runner = build_rule_runner(
        MockGeneratedTarget.register_plugin_field(PythonResolveField),
        MockTargetGenerator.register_plugin_field(PythonResolveField),
    )
    assert_generated(
        rule_runner,
        build_content="generator(tags=['t1'], sources=['f1.ext'], python_resolve='gpu')",
        files=["f1.ext"],
        address=Address("demo"),
        expected_targets={
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t1"],
                    PythonResolveField.alias: "gpu",
                },
                union_membership=rule_runner.union_membership,
                address=Address("demo", relative_file_path="f1.ext"),
                residence_dir="demo",
            )
        },
    )


def test_parametrize_target_with_a_plugin_field() -> None:
    rule_runner = build_rule_runner(
        MockGeneratedTarget.register_plugin_field(PythonResolveField),
    )
    assert_generated(
        rule_runner,
        build_content="generated(tags=['t1'], source='f1.ext', python_resolve=parametrize(g='gpu',c='cpu'))",
        files=["f1.ext"],
        address=Address("demo"),
        expected_targets={
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t1"],
                    PythonResolveField.alias: "gpu",
                },
                union_membership=rule_runner.union_membership,
                address=Address("demo", parameters={"python_resolve": "g"}),
                residence_dir="demo",
            ),
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t1"],
                    PythonResolveField.alias: "cpu",
                },
                union_membership=rule_runner.union_membership,
                address=Address("demo", parameters={"python_resolve": "c"}),
                residence_dir="demo",
            ),
        },
    )


def test_generate_target_with_parametrized_moved_field() -> None:
    rule_runner = build_rule_runner(
        MockGeneratedTarget.register_plugin_field(PythonResolveField),
    )
    assert_generated(
        rule_runner,
        build_content="generator(tags=parametrize(pt1=['t1'], pt2=['t2']), sources=['f1.ext'])",
        files=["f1.ext"],
        address=Address("demo"),
        expected_targets={
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t1"],
                },
                union_membership=rule_runner.union_membership,
                address=Address("demo", relative_file_path="f1.ext", parameters={"tags": "pt1"}),
                residence_dir="demo",
            ),
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t2"],
                },
                union_membership=rule_runner.union_membership,
                address=Address("demo", relative_file_path="f1.ext", parameters={"tags": "pt2"}),
                residence_dir="demo",
            ),
        },
    )


def test_generate_target_with_parametrized_moved_plugin_field() -> None:
    rule_runner = build_rule_runner(
        MockGeneratedTarget.register_plugin_field(PythonResolveField),
        MockTargetGenerator.register_plugin_field(PythonResolveField, as_moved_field=True),
    )
    assert_generated(
        rule_runner,
        build_content="generator(tags=['t1'], sources=['f1.ext'], python_resolve=parametrize(g='gpu',c='cpu'))",
        files=["f1.ext"],
        address=Address("demo"),
        expected_targets={
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t1"],
                    PythonResolveField.alias: "gpu",
                },
                union_membership=rule_runner.union_membership,
                address=Address(
                    "demo", relative_file_path="f1.ext", parameters={"python_resolve": "g"}
                ),
                residence_dir="demo",
            ),
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t1"],
                    PythonResolveField.alias: "cpu",
                },
                union_membership=rule_runner.union_membership,
                address=Address(
                    "demo", relative_file_path="f1.ext", parameters={"python_resolve": "c"}
                ),
                residence_dir="demo",
            ),
        },
    )


def test_cannot_parametrize_generated_target_with_copied_plugin_field() -> None:
    rule_runner = build_rule_runner(
        MockGeneratedTarget.register_plugin_field(PythonResolveField),
        MockTargetGenerator.register_plugin_field(PythonResolveField),  # no as_moved_field=True
    )
    with pytest.raises(ExecutionError) as e:
        assert_generated(
            rule_runner,
            build_content="generator(tags=['t1'], sources=['f1.ext'], python_resolve=parametrize(g='gpu',c='cpu'))",
            files=["f1.ext"],
            address=Address("demo"),
        )

    (field_exception,) = e.value.wrapped_exceptions
    assert isinstance(field_exception, InvalidFieldException)
    msg = str(field_exception)

    assert "Only fields which will be moved to generated targets may be parametrized" in msg
