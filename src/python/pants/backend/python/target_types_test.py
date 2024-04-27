# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference.rules import UnownedDependencyError, import_rules
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.target_types import (
    ConsoleScript,
    EntryPoint,
    Executable,
    PexBinariesGeneratorTarget,
    PexBinary,
    PexEntryPointField,
    PexExecutableField,
    PexScriptField,
    PythonDistribution,
    PythonRequirementsField,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
    ResolvePythonDistributionEntryPointsRequest,
    normalize_module_mapping,
)
from pants.backend.python.target_types_rules import (
    InferPexBinaryEntryPointDependency,
    InferPythonDistributionDependencies,
    PexBinaryEntryPointDependencyInferenceFieldSet,
    PythonDistributionDependenciesInferenceFieldSet,
    resolve_pex_entry_point,
)
from pants.backend.python.util_rules import python_sources
from pants.core.goals.generate_lockfiles import UnrecognizedResolveNamesError
from pants.engine.addresses import Address
from pants.engine.internals.graph import _TargetParametrizations, _TargetParametrizationsRequest
from pants.engine.internals.parametrize import Parametrize
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import (
    InferredDependencies,
    InvalidFieldException,
    InvalidFieldTypeException,
    InvalidTargetException,
    Tags,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict
from pants.util.pip_requirement import PipRequirement
from pants.util.strutil import softwrap


def test_pex_binary_validation() -> None:
    def create_tgt(
        *, script: str | None = None, executable: str | None = None, entry_point: str | None = None
    ) -> PexBinary:
        return PexBinary(
            {
                PexScriptField.alias: script,
                PexExecutableField.alias: executable,
                PexEntryPointField.alias: entry_point,
            },
            Address("", target_name="t"),
        )

    with pytest.raises(InvalidTargetException):
        create_tgt(script="foo", executable="foo", entry_point="foo")
    with pytest.raises(InvalidTargetException):
        create_tgt(script="foo", executable="foo")
    with pytest.raises(InvalidTargetException):
        create_tgt(script="foo", entry_point="foo")
    with pytest.raises(InvalidTargetException):
        create_tgt(executable="foo", entry_point="foo")
    assert create_tgt(script="foo")[PexScriptField].value == ConsoleScript("foo")
    assert create_tgt(executable="foo")[PexExecutableField].value == Executable("foo")
    assert create_tgt(entry_point="foo")[PexEntryPointField].value == EntryPoint("foo")


def test_entry_point_validation(caplog) -> None:
    addr = Address("src/python/project")

    with pytest.raises(InvalidFieldException):
        PexEntryPointField(" ", addr)
    with pytest.raises(InvalidFieldException):
        PexEntryPointField("modue:func:who_knows_what_this_is", addr)
    with pytest.raises(InvalidFieldException):
        PexEntryPointField(":func", addr)

    ep = "custom.entry_point:"
    with caplog.at_level(logging.WARNING):
        assert EntryPoint("custom.entry_point") == PexEntryPointField(ep, addr).value

    assert len(caplog.record_tuples) == 1
    _, levelno, message = caplog.record_tuples[0]
    assert logging.WARNING == levelno
    assert ep in message
    assert str(addr) in message


def test_resolve_pex_binary_entry_point() -> None:
    rule_runner = RuleRunner(
        rules=[
            resolve_pex_entry_point,
            QueryRule(ResolvedPexEntryPoint, [ResolvePexEntryPointRequest]),
        ]
    )

    def assert_resolved(
        *, entry_point: str | None, expected: EntryPoint | None, is_file: bool
    ) -> None:
        addr = Address("src/python/project")
        rule_runner.write_files(
            {
                "src/python/project/app.py": "",
                "src/python/project/f2.py": "",
            }
        )
        ep_field = PexEntryPointField(entry_point, addr)
        result = rule_runner.request(ResolvedPexEntryPoint, [ResolvePexEntryPointRequest(ep_field)])
        assert result.val == expected
        assert result.file_name_used == is_file

    # Full module provided.
    assert_resolved(
        entry_point="custom.entry_point", expected=EntryPoint("custom.entry_point"), is_file=False
    )
    assert_resolved(
        entry_point="custom.entry_point:func",
        expected=EntryPoint.parse("custom.entry_point:func"),
        is_file=False,
    )

    # File names are expanded into the full module path.
    assert_resolved(entry_point="app.py", expected=EntryPoint(module="project.app"), is_file=True)
    assert_resolved(
        entry_point="app.py:func",
        expected=EntryPoint(module="project.app", function="func"),
        is_file=True,
    )

    with pytest.raises(ExecutionError):
        assert_resolved(
            entry_point="doesnt_exist.py", expected=EntryPoint("doesnt matter"), is_file=True
        )
    # Resolving >1 file is an error.
    with pytest.raises(ExecutionError):
        assert_resolved(entry_point="*.py", expected=EntryPoint("doesnt matter"), is_file=True)


@pytest.mark.parametrize(
    ["python_infer_unowned_dependency_behavior"], [("ignore",), ("warning",), ("error",)]
)
def test_infer_pex_binary_entry_point_dependency(
    python_infer_unowned_dependency_behavior, caplog
) -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_types_rules.rules(),
            *import_rules(),
            QueryRule(InferredDependencies, [InferPexBinaryEntryPointDependency]),
        ],
        target_types=[PexBinary, PythonRequirementTarget, PythonSourcesGeneratorTarget],
    )
    rule_runner.set_options(
        [f"--python-infer-unowned-dependency-behavior={python_infer_unowned_dependency_behavior}"]
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(
                    name='ansicolors',
                    requirements=['ansicolors'],
                    modules=['colors'],
                )
                """
            ),
            "project/app.py": "",
            "project/ambiguous.py": "",
            "project/ambiguous_in_another_root.py": "",
            "project/BUILD": dedent(
                """\
                python_sources(sources=['app.py'])
                pex_binary(name='first_party', entry_point='project.app')
                pex_binary(name='first_party_func', entry_point='project.app:func')
                pex_binary(name='first_party_shorthand', entry_point='app.py')
                pex_binary(name='first_party_shorthand_func', entry_point='app.py:func')
                pex_binary(name='third_party', entry_point='colors')
                pex_binary(name='third_party_func', entry_point='colors:func')
                pex_binary(name='unrecognized', entry_point='who_knows.module')

                python_sources(name="dep1", sources=["ambiguous.py"])
                python_sources(name="dep2", sources=["ambiguous.py"])
                pex_binary(name="ambiguous", entry_point="ambiguous.py")
                pex_binary(
                    name="disambiguated",
                    entry_point="ambiguous.py",
                    dependencies=["!./ambiguous.py:dep2"],
                )

                python_sources(
                    name="ambiguous_in_another_root", sources=["ambiguous_in_another_root.py"]
                )
                pex_binary(
                    name="another_root__file_used", entry_point="ambiguous_in_another_root.py"
                )
                pex_binary(
                    name="another_root__module_used",
                    entry_point="project.ambiguous_in_another_root",
                )
                """
            ),
            "src/py/project/ambiguous_in_another_root.py": "",
            "src/py/project/BUILD.py": "python_sources()",
        }
    )

    def assert_inferred(address: Address, *, expected: Address | None) -> None:
        tgt = rule_runner.get_target(address)
        inferred = rule_runner.request(
            InferredDependencies,
            [
                InferPexBinaryEntryPointDependency(
                    PexBinaryEntryPointDependencyInferenceFieldSet.create(tgt)
                )
            ],
        )
        assert inferred == InferredDependencies([expected] if expected else [])

    assert_inferred(
        Address("project", target_name="first_party"),
        expected=Address("project", relative_file_path="app.py"),
    )
    assert_inferred(
        Address("project", target_name="first_party_func"),
        expected=Address("project", relative_file_path="app.py"),
    )
    assert_inferred(
        Address("project", target_name="first_party_shorthand"),
        expected=Address("project", relative_file_path="app.py"),
    )
    assert_inferred(
        Address("project", target_name="first_party_shorthand_func"),
        expected=Address("project", relative_file_path="app.py"),
    )
    assert_inferred(
        Address("project", target_name="third_party"),
        expected=Address("", target_name="ansicolors"),
    )
    assert_inferred(
        Address("project", target_name="third_party_func"),
        expected=Address("", target_name="ansicolors"),
    )
    assert_inferred(Address("project", target_name="unrecognized"), expected=None)

    # Warn if there's ambiguity, meaning we cannot infer.
    caplog.clear()
    if python_infer_unowned_dependency_behavior == "error":
        with pytest.raises(ExecutionError) as ambiguous_error:
            assert_inferred(Address("project", target_name="ambiguous"), expected=None)
        assert isinstance(ambiguous_error.value.wrapped_exceptions[0], UnownedDependencyError)
    else:
        assert_inferred(Address("project", target_name="ambiguous"), expected=None)
    assert (
        softwrap(
            """
            project:ambiguous has the field `entry_point='ambiguous.py'`, which maps to the Python
            module `project.ambiguous`
            """
        )
        in caplog.text
    )
    assert "['project/ambiguous.py:dep1', 'project/ambiguous.py:dep2']" in caplog.text

    # assert that the message for the PEX entrypoint was respected
    if python_infer_unowned_dependency_behavior == "warning":
        assert len(caplog.records) == 2
        assert (
            "The entrypoint EntryPoint(module='ambiguous.py', function=None) might refer to the following"
            in caplog.text
        )
    else:
        # the "error" case raises it as an error, so it doesn't appear in caplog
        assert len(caplog.records) == 1

    # Test that ignores can disambiguate an otherwise ambiguous entry point. Ensure we don't log a
    # warning about ambiguity.
    caplog.clear()
    assert_inferred(
        Address("project", target_name="disambiguated"),
        expected=Address("project", target_name="dep1", relative_file_path="ambiguous.py"),
    )
    assert not caplog.records

    # Test that using a file path results in ignoring all targets which are not an ancestor. We can
    # do this because we know the file name must be in the current directory or subdir of the
    # `pex_binary`.
    assert_inferred(
        Address("project", target_name="another_root__file_used"),
        expected=Address(
            "project",
            target_name="ambiguous_in_another_root",
            relative_file_path="ambiguous_in_another_root.py",
        ),
    )

    caplog.clear()
    if python_infer_unowned_dependency_behavior == "error":
        with pytest.raises(ExecutionError) as ambiguous_error_2:
            assert_inferred(
                Address("project", target_name="another_root__module_used"), expected=None
            )
        assert isinstance(ambiguous_error_2.value.wrapped_exceptions[0], UnownedDependencyError)
    else:
        assert_inferred(Address("project", target_name="another_root__module_used"), expected=None)
    assert (
        softwrap(
            """
            ['project/ambiguous_in_another_root.py:ambiguous_in_another_root',
            'src/py/project/ambiguous_in_another_root.py']
            """
        )
        in caplog.text
    )
    if python_infer_unowned_dependency_behavior == "warning":
        assert len(caplog.records) == 2
        assert (
            "The entrypoint EntryPoint(module='project.ambiguous_in_another_root', function=None) might refer to the following"
            in caplog.text
        )
    else:
        # the "error" case raises it as an error, so it doesn't appear in caplog
        assert len(caplog.records) == 1

    # Test that we can turn off the inference.
    rule_runner.set_options(["--no-python-infer-entry-points"])
    assert_inferred(Address("project", target_name="first_party"), expected=None)


def test_requirements_field() -> None:
    raw_value = (
        "argparse==1.2.1",
        "configparser ; python_version<'3'",
        "pip@ git+https://github.com/pypa/pip.git",
    )
    parsed_value = tuple(PipRequirement.parse(v) for v in raw_value)

    assert PythonRequirementsField(raw_value, Address("demo")).value == parsed_value

    # Macros can pass pre-parsed PipRequirement objects.
    assert PythonRequirementsField(parsed_value, Address("demo")).value == parsed_value

    # Reject invalid types.
    with pytest.raises(InvalidFieldTypeException):
        PythonRequirementsField("sneaky_str", Address("demo"))
    with pytest.raises(InvalidFieldTypeException):
        PythonRequirementsField([1, 2], Address("demo"))

    # Give a nice error message if the requirement can't be parsed.
    with pytest.raises(InvalidFieldException) as exc:
        PythonRequirementsField(["not valid! === 3.1"], Address("demo"))
    assert (
        softwrap(
            f"""
            Invalid requirement 'not valid! === 3.1' in the '{PythonRequirementsField.alias}'
            field for the target demo:
            """
        )
        in str(exc.value)
    )


def test_resolve_python_distribution_entry_points_required_fields() -> None:
    with pytest.raises(AssertionError):
        # either `entry_points_field` or `provides_field` is required
        ResolvePythonDistributionEntryPointsRequest()


def test_infer_python_distribution_dependencies() -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_types_rules.rules(),
            *import_rules(),
            *python_sources.rules(),
            QueryRule(InferredDependencies, [InferPythonDistributionDependencies]),
        ],
        target_types=[
            PythonDistribution,
            PythonRequirementTarget,
            PythonSourcesGeneratorTarget,
            PexBinary,
        ],
        objects={"setup_py": PythonArtifact},
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(
                    name='ansicolors',
                    requirements=['ansicolors'],
                    modules=['colors'],
                )
                """
            ),
            "project/app.py": "",
            "project/BUILD": dedent(
                """\
                pex_binary(name="my_binary", entry_point="who_knows.module:main")

                python_sources(name="my_library", sources=["app.py"])

                python_distribution(
                    name="dist-a",
                    provides=setup_py(
                        name='my-dist-a'
                    ),
                    entry_points={
                        "console_scripts":{
                            "my_cmd": ":my_binary",
                        },
                    },
                )

                python_distribution(
                    name="dist-b",
                    provides=setup_py(
                        name="my-dist-b"
                    ),
                    entry_points={
                        "console_scripts":{
                            "b_cmd": "project.app:main",
                            "cmd_2": "//project:my_binary",
                        }
                    },
                )

                python_distribution(
                    name="third_dep",
                    provides=setup_py(name="my-third"),
                    entry_points={
                        "color-plugins":{
                            "my-ansi-colors": "colors",
                        }
                    }
                )

                python_distribution(
                    name="third_dep2",
                    provides=setup_py(
                        name="my-third",
                        entry_points={
                            "console_scripts":{
                                "my-cmd": ":my_binary",
                                "main": "project.app:main",
                            },
                            "color-plugins":{
                                "my-ansi-colors": "colors",
                            }
                        }
                    )
                )
                """
            ),
            "who_knows/module.py": "",
            "who_knows/BUILD": dedent(
                """\
                python_sources(name="random_lib", sources=["module.py"])
                """
            ),
        }
    )

    def assert_inferred(address: Address, expected: list[Address]) -> None:
        tgt = rule_runner.get_target(address)
        inferred = rule_runner.request(
            InferredDependencies,
            [
                InferPythonDistributionDependencies(
                    PythonDistributionDependenciesInferenceFieldSet.create(tgt)
                )
            ],
        )
        assert inferred == InferredDependencies(expected)

    assert_inferred(
        Address("project", target_name="dist-a"),
        [Address("project", target_name="my_binary")],
    )

    assert_inferred(
        Address("project", target_name="dist-b"),
        [
            Address("project", target_name="my_binary"),
            Address("project", relative_file_path="app.py", target_name="my_library"),
        ],
    )

    assert_inferred(
        Address("project", target_name="third_dep"),
        [
            Address("", target_name="ansicolors"),
        ],
    )

    assert_inferred(
        Address("project", target_name="third_dep2"),
        [
            Address("", target_name="ansicolors"),
            Address("project", target_name="my_binary"),
            Address("project", relative_file_path="app.py", target_name="my_library"),
        ],
    )


@pytest.mark.parametrize(
    "unrecognized,bad_entry_str,name_str",
    (
        (["fake"], "fake", "name"),
        (["fake1", "fake2"], "['fake1', 'fake2']", "names"),
    ),
)
def test_unrecognized_resolve_names_error(
    unrecognized: list[str], bad_entry_str: str, name_str: str
) -> None:
    with pytest.raises(UnrecognizedResolveNamesError) as exc:
        raise UnrecognizedResolveNamesError(
            unrecognized, ["valid1", "valid2", "valid3"], description_of_origin="foo"
        )
    assert (
        softwrap(
            f"""
            Unrecognized resolve {name_str} from foo:
            {bad_entry_str}\n\nAll valid resolve names: ['valid1', 'valid2', 'valid3']
            """
        )
        in str(exc.value)
    )


@pytest.mark.parametrize(
    ["raw_value", "expected"],
    (
        (None, {}),
        ({"new-dist": ["new_module"]}, {"new-dist": ("new_module",)}),
        ({"PyYAML": ["custom_yaml"]}, {"pyyaml": ("custom_yaml",)}),
    ),
)
def test_normalize_module_mapping(
    raw_value: dict[str, Iterable[str]] | None, expected: dict[str, tuple[str, ...]]
) -> None:
    assert normalize_module_mapping(raw_value) == FrozenDict(expected)


# -----------------------------------------------------------------------------------------------
# Generate targets
# -----------------------------------------------------------------------------------------------


def test_pex_binary_targets() -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_types_rules.rules(),
            *import_rules(),
            *python_sources.rules(),
            QueryRule(_TargetParametrizations, [_TargetParametrizationsRequest]),
        ],
        target_types=[PexBinariesGeneratorTarget],
    )
    rule_runner.write_files(
        {
            "src/py/BUILD": dedent(
                """\
                pex_binaries(
                    name="pexes",
                    entry_points=[
                        "f1.py",
                        "f2:foo",
                        "subdir.f.py",
                        "subdir.f:main",
                    ],
                    overrides={
                        'f2:foo': {'tags': ['overridden']},
                        'subdir.f.py': {'tags': ['overridden']},
                    }
                )
                """
            ),
        }
    )

    def gen_pex_binary_tgt(entry_point: str, tags: list[str] | None = None) -> PexBinary:
        return PexBinary(
            {PexEntryPointField.alias: entry_point, Tags.alias: tags},
            Address("src/py", target_name="pexes", generated_name=entry_point.replace(":", "-")),
            residence_dir="src/py",
        )

    result = rule_runner.request(
        _TargetParametrizations,
        [
            _TargetParametrizationsRequest(
                Address("src/py", target_name="pexes"), description_of_origin="tests"
            )
        ],
    ).parametrizations.values()
    assert set(result) == {
        gen_pex_binary_tgt("f1.py"),
        gen_pex_binary_tgt("f2:foo", tags=["overridden"]),
        gen_pex_binary_tgt("subdir.f.py", tags=["overridden"]),
        gen_pex_binary_tgt("subdir.f:main"),
    }


def assert_inferred(rule_runner: RuleRunner, address: Address, expected: list[Address]) -> None:
    tgt = rule_runner.get_target(address)
    inferred = rule_runner.request(
        InferredDependencies,
        [
            InferPexBinaryEntryPointDependency(
                PexBinaryEntryPointDependencyInferenceFieldSet.create(tgt)
            )
        ],
    )
    assert inferred == InferredDependencies(expected)


def test_20806() -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_types_rules.rules(),
            *import_rules(),
            *python_sources.rules(),
            QueryRule(InferredDependencies, [InferPythonDistributionDependencies]),
        ],
        target_types=[
            PythonDistribution,
            PythonRequirementTarget,
            PythonSourceTarget,
            PexBinary,
        ],
        objects={"parametrize": Parametrize},
    )

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
            python_source(name="src", source="example.py", tags=parametrize(a=["a"], b=["b"]))

            pex_binary(name="ambiguous", entry_point="./example.py")

            pex_binary(name="with-target", entry_point="./example.py:src@tags=a")

            pex_binary(name="with-deps", entry_point="./example.py", dependencies=[":src@tags=a"])

            pex_binary(name="with-ignore-only", entry_point="./example.py", dependencies=[ "!:src@tags=b"])
            """
            ),
            "example.py": "print('worked!')",
        }
    )

    # The ambiguous should not be disambiguated
    assert_inferred(
        rule_runner,
        Address(spec_path="", target_name="ambiguous"),
        [],
    )

    # Using an explicit target is not standard (the entry is actually a Python entrypoint, not a Pants target)
    assert_inferred(
        rule_runner,
        Address(spec_path="", target_name="with-target"),
        [Address(spec_path="", target_name="src", parameters={"tags": "a"})],
    )

    # Explicitly providing the dep should resolve the ambiguity
    assert_inferred(
        rule_runner,
        Address(spec_path="", target_name="with-deps"),
        [Address(spec_path="", target_name="src", parameters={"tags": "a"})],
    )

    assert_inferred(
        rule_runner,
        Address(spec_path="", target_name="with-ignore-only"),
        [Address(spec_path="", target_name="src", parameters={"tags": "a"})],
    )
