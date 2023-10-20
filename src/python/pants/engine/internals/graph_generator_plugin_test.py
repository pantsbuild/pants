from __future__ import annotations

import os

import pytest

from pants.base.specs import Specs
from pants.engine.addresses import Addresses
from pants.engine.environment import EnvironmentName
from pants.engine.internals.graph import _DependencyMapping, _DependencyMappingRequest, Owners, OwnersRequest
from pants.engine.internals.native_engine import Address
from pants.engine.internals.parametrize import _TargetParametrizations, _TargetParametrizationsRequest, Parametrize
from pants.engine.rules import QueryRule
from pants.engine.target import FieldDefaultFactoryRequest, TargetFilesGenerator, Target, SingleSourceField, Tags, \
    MultipleSourcesField, OverridesField, AllTargets, StringField
from pants.engine.unions import UnionRule
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
        MockSingleSourceField)



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
            QueryRule(_DependencyMapping, [_DependencyMappingRequest]),
            QueryRule(_TargetParametrizations, [_TargetParametrizationsRequest, EnvironmentName]),
            QueryRule(Owners, [OwnersRequest]),
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
    assert expected_targets == set(targets)


def test_generate_single_simple() -> None:
    rule_runner = build_rule_runner()
    assert_generated(
        rule_runner,
        build_content = "generator(tags=['t1'], sources=['f1.ext'])",
        files = ["f1.ext"],
        address = Address("demo"),
        expected_targets = {MockGeneratedTarget(
            unhydrated_values={
                SingleSourceField.alias: "f1.ext",
                Tags.alias: ["t1"],
            },
            address=Address("demo", relative_file_path="f1.ext"),
            residence_dir='demo',
        )}
    )


def test_non_generated_single() -> None:
    rule_runner = build_rule_runner()

    assert_generated(
        rule_runner,
        build_content = "generated(tags=['t1'], source='f1.ext')",
        files = ["f1.ext"],
        address = Address("demo"),
        expected_targets = {MockGeneratedTarget(
            unhydrated_values={
                SingleSourceField.alias: "f1.ext",
                Tags.alias: ["t1"],
            },
            address=Address("demo"),
            residence_dir='demo',
        )}
    )


def test_non_generated_single_plugin_field() -> None:
    rule_runner = build_rule_runner(
        MockGeneratedTarget.register_plugin_field(PythonResolveField),
    )
    assert_generated(
        rule_runner,
        build_content = "generated(tags=['t1'], source='f1.ext', python_resolve='gpu')",
        files = ["f1.ext"],
        address = Address("demo"),
        expected_targets={
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t1"],
                    PythonResolveField.alias: "gpu",
                },
                union_membership=rule_runner.union_membership,
                address=Address("demo"),
                residence_dir='demo',
            )
        }
    )


def test_generated_single_plugin_field() -> None:
    rule_runner = build_rule_runner(
            MockGeneratedTarget.register_plugin_field(PythonResolveField),
            MockTargetGenerator.register_plugin_field(PythonResolveField),
    )
    assert_generated(
        rule_runner,
        build_content = "generator(tags=['t1'], sources=['f1.ext'], python_resolve='gpu')",
        files = ["f1.ext"],
        address = Address("demo"),
        expected_targets = {MockGeneratedTarget(
            unhydrated_values={
                SingleSourceField.alias: "f1.ext",
                Tags.alias: ["t1"],
                PythonResolveField.alias: "gpu",
            },
            union_membership=rule_runner.union_membership,
            address=Address("demo", relative_file_path="f1.ext"),
            residence_dir='demo',
        )}
    )


def test_non_generated_single_plugin_field_parametrized() -> None:
    rule_runner = build_rule_runner(
            MockGeneratedTarget.register_plugin_field(PythonResolveField),
    )
    assert_generated(
        rule_runner,
        build_content = "generated(tags=['t1'], source='f1.ext', python_resolve=parametrize(g='gpu',c='cpu'))",
        files = ["f1.ext"],
        address = Address("demo"),
        expected_targets = {
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t1"],
                    PythonResolveField.alias: "gpu",
                },
                union_membership=rule_runner.union_membership,
                address=Address("demo", parameters={'python_resolve': 'g'}),
                residence_dir='demo',
            ),
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t1"],
                    PythonResolveField.alias: "cpu",
                },
                union_membership=rule_runner.union_membership,
                address=Address("demo", parameters={'python_resolve': 'c'}),
                residence_dir='demo',
            ),
        }

    )


def test_moved_field_parametrized() -> None:
    rule_runner = build_rule_runner(
            MockGeneratedTarget.register_plugin_field(PythonResolveField),
    )
    assert_generated(
        rule_runner,
        build_content = "generator(tags=parametrize(pt1=['t1'], pt2=['t2']), sources=['f1.ext'])",
        files = ["f1.ext"],
        address = Address("demo"),
        expected_targets = {
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t1"],
                },
                union_membership=rule_runner.union_membership,
                address=Address("demo", relative_file_path="f1.ext", parameters={'tags': 'pt1'}),
                residence_dir='demo',
            ),
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t2"],
                },
                union_membership=rule_runner.union_membership,
                address=Address("demo", relative_file_path="f1.ext", parameters={'tags': 'pt2'}),
                residence_dir='demo',
            ),
        }
    )


def test_generated_plugin_field_parametrized() -> None:
    rule_runner = build_rule_runner(
        MockGeneratedTarget.register_plugin_field(PythonResolveField),
        MockTargetGenerator.register_plugin_field(PythonResolveField, as_moved_field=True),
    )
    assert_generated(
        build_rule_runner(
            MockGeneratedTarget.register_plugin_field(PythonResolveField),
            MockTargetGenerator.register_plugin_field(PythonResolveField, as_moved_field=True),
        ),
        build_content = "generator(tags=['t1'], sources=['f1.ext'], python_resolve=parametrize(g='gpu',c='cpu'))",
        files = ["f1.ext"],
        address = Address("demo"),
        expected_targets = {
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t1"],
                    PythonResolveField.alias: "gpu",
                },
                union_membership=rule_runner.union_membership,
                address=Address("demo", relative_file_path="f1.ext", parameters={'python_resolve': 'g'}),
                residence_dir='demo',
            ),
            MockGeneratedTarget(
                unhydrated_values={
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["t1"],
                    PythonResolveField.alias: "cpu",
                },
                union_membership=rule_runner.union_membership,
                address=Address("demo", relative_file_path="f1.ext", parameters={'python_resolve': 'c'}),
                residence_dir='demo',
            ),
        }
    )
