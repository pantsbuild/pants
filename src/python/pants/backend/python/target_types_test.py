# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from textwrap import dedent
from typing import Dict, Iterable, List, Optional, Tuple

import pytest
from _pytest.logging import LogCaptureFixture
from pkg_resources import Requirement

from pants.backend.python.dependency_inference.default_module_mapping import DEFAULT_MODULE_MAPPING
from pants.backend.python.dependency_inference.rules import import_rules
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.target_types import (
    EntryPoint,
    ModuleMappingField,
    PexBinary,
    PexBinaryDependencies,
    PexEntryPointField,
    PythonDistribution,
    PythonDistributionDependencies,
    PythonLibrary,
    PythonRequirementLibrary,
    PythonRequirementsField,
    PythonTestsTimeout,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
    parse_requirements_file,
)
from pants.backend.python.target_types_rules import (
    InjectPexBinaryEntryPointDependency,
    InjectPythonDistributionDependencies,
    inject_pex_binary_entry_point_dependency,
    inject_python_distribution_dependencies,
    resolve_pex_entry_point,
)
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import (
    InjectedDependencies,
    InvalidFieldException,
    InvalidFieldTypeException,
)
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict


def test_timeout_validation() -> None:
    with pytest.raises(InvalidFieldException):
        PythonTestsTimeout(-100, address=Address("", target_name="tests"))
    with pytest.raises(InvalidFieldException):
        PythonTestsTimeout(0, address=Address("", target_name="tests"))
    assert PythonTestsTimeout(5, address=Address("", target_name="tests")).value == 5


def test_timeout_calculation() -> None:
    def assert_timeout_calculated(
        *,
        field_value: Optional[int],
        expected: Optional[int],
        global_default: Optional[int] = None,
        global_max: Optional[int] = None,
        timeouts_enabled: bool = True,
    ) -> None:
        field = PythonTestsTimeout(field_value, address=Address("", target_name="tests"))
        pytest = create_subsystem(
            PyTest,
            timeouts=timeouts_enabled,
            timeout_default=global_default,
            timeout_maximum=global_max,
        )
        assert field.calculate_from_global_options(pytest) == expected

    assert_timeout_calculated(field_value=10, expected=10)
    assert_timeout_calculated(field_value=20, global_max=10, expected=10)
    assert_timeout_calculated(field_value=None, global_default=20, expected=20)
    assert_timeout_calculated(field_value=None, expected=None)
    assert_timeout_calculated(field_value=None, global_default=20, global_max=10, expected=10)
    assert_timeout_calculated(field_value=10, timeouts_enabled=False, expected=None)


@pytest.mark.parametrize(
    ["entry_point", "expected"],
    (
        ("<none>", []),
        ("path.to.module", []),
        ("path.to.module:func", []),
        ("lambda.py", ["project/dir/lambda.py"]),
        ("lambda.py:func", ["project/dir/lambda.py"]),
    ),
)
def test_entry_point_filespec(entry_point: Optional[str], expected: List[str]) -> None:
    field = PexEntryPointField(entry_point, address=Address("project/dir"))
    assert field.filespec == {"includes": expected}


def test_entry_point_validation(caplog: LogCaptureFixture) -> None:
    addr = Address("src/python/project")

    with pytest.raises(InvalidFieldException):
        PexEntryPointField(" ", address=addr)
    with pytest.raises(InvalidFieldException):
        PexEntryPointField("modue:func:who_knows_what_this_is", address=addr)
    with pytest.raises(InvalidFieldException):
        PexEntryPointField(":func", address=addr)

    ep = "custom.entry_point:"
    with caplog.at_level(logging.WARNING):
        assert EntryPoint("custom.entry_point") == PexEntryPointField(ep, address=addr).value

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

    def assert_resolved(*, entry_point: Optional[str], expected: Optional[EntryPoint]) -> None:
        addr = Address("src/python/project")
        rule_runner.create_file("src/python/project/app.py")
        rule_runner.create_file("src/python/project/f2.py")
        ep_field = PexEntryPointField(entry_point, address=addr)
        result = rule_runner.request(ResolvedPexEntryPoint, [ResolvePexEntryPointRequest(ep_field)])
        assert result.val == expected

    # Full module provided.
    assert_resolved(entry_point="custom.entry_point", expected=EntryPoint("custom.entry_point"))
    assert_resolved(
        entry_point="custom.entry_point:func", expected=EntryPoint.parse("custom.entry_point:func")
    )

    # File names are expanded into the full module path.
    assert_resolved(entry_point="app.py", expected=EntryPoint(module="project.app"))
    assert_resolved(
        entry_point="app.py:func", expected=EntryPoint(module="project.app", function="func")
    )

    # We special case the strings `<none>` and `<None>`.
    assert_resolved(entry_point="<none>", expected=None)
    assert_resolved(entry_point="<None>", expected=None)

    with pytest.raises(ExecutionError):
        assert_resolved(entry_point="doesnt_exist.py", expected=EntryPoint("doesnt matter"))
    # Resolving >1 file is an error.
    with pytest.raises(ExecutionError):
        assert_resolved(entry_point="*.py", expected=EntryPoint("doesnt matter"))


def test_inject_pex_binary_entry_point_dependency() -> None:
    rule_runner = RuleRunner(
        rules=[
            inject_pex_binary_entry_point_dependency,
            resolve_pex_entry_point,
            *import_rules(),
            QueryRule(InjectedDependencies, [InjectPexBinaryEntryPointDependency]),
        ],
        target_types=[PexBinary, PythonRequirementLibrary, PythonLibrary],
    )
    rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            python_requirement_library(
                name='ansicolors',
                requirements=['ansicolors'],
                module_mapping={'ansicolors': ['colors']},
            )
            """
        ),
    )
    rule_runner.create_files("project", ["app.py", "self.py"])
    rule_runner.add_to_build_file(
        "project",
        dedent(
            """\
            python_library(sources=['app.py'])
            pex_binary(name='first_party', entry_point='project.app')
            pex_binary(name='first_party_func', entry_point='project.app:func')
            pex_binary(name='first_party_shorthand', entry_point='app.py:func')
            pex_binary(name='first_party_shorthand_func', entry_point='app.py:func')
            pex_binary(name='third_party', entry_point='colors')
            pex_binary(name='third_party_func', entry_point='colors:func')
            pex_binary(name='unrecognized', entry_point='who_knows.module')
            """
        ),
    )

    def assert_injected(address: Address, *, expected: Optional[Address]) -> None:
        tgt = rule_runner.get_target(address)
        injected = rule_runner.request(
            InjectedDependencies,
            [InjectPexBinaryEntryPointDependency(tgt[PexBinaryDependencies])],
        )
        assert injected == InjectedDependencies([expected] if expected else [])

    assert_injected(
        Address("project", target_name="first_party"),
        expected=Address("project", relative_file_path="app.py"),
    )
    assert_injected(
        Address("project", target_name="first_party_func"),
        expected=Address("project", relative_file_path="app.py"),
    )
    assert_injected(
        Address("project", target_name="first_party_shorthand"),
        expected=Address("project", relative_file_path="app.py"),
    )
    assert_injected(
        Address("project", target_name="first_party_shorthand_func"),
        expected=Address("project", relative_file_path="app.py"),
    )
    assert_injected(
        Address("project", target_name="third_party"),
        expected=Address("", target_name="ansicolors"),
    )
    assert_injected(
        Address("project", target_name="third_party_func"),
        expected=Address("", target_name="ansicolors"),
    )
    assert_injected(Address("project", target_name="unrecognized"), expected=None)

    # Test that we can turn off the injection.
    rule_runner.set_options(["--no-python-infer-entry-points"])
    assert_injected(Address("project", target_name="first_party"), expected=None)


def test_requirements_field() -> None:
    raw_value = (
        "argparse==1.2.1",
        "configparser ; python_version<'3'",
        "pip@ git+https://github.com/pypa/pip.git",
    )
    parsed_value = tuple(Requirement.parse(v) for v in raw_value)

    assert PythonRequirementsField(raw_value, address=Address("demo")).value == parsed_value

    # Macros can pass pre-parsed Requirement objects.
    assert PythonRequirementsField(parsed_value, address=Address("demo")).value == parsed_value

    # Reject invalid types.
    with pytest.raises(InvalidFieldTypeException):
        PythonRequirementsField("sneaky_str", address=Address("demo"))
    with pytest.raises(InvalidFieldTypeException):
        PythonRequirementsField([1, 2], address=Address("demo"))

    # Give a nice error message if the requirement can't be parsed.
    with pytest.raises(InvalidFieldException) as exc:
        PythonRequirementsField(["not valid! === 3.1"], address=Address("demo"))
    assert (
        "Invalid requirement 'not valid! === 3.1' in the 'requirements' field for the "
        "target demo:"
    ) in str(exc.value)

    # Give a nice error message if it looks like they're trying to use pip VCS-style requirements.
    with pytest.raises(InvalidFieldException) as exc:
        PythonRequirementsField(
            ["git+https://github.com/pypa/pip.git#egg=pip"], address=Address("demo")
        )
    assert "It looks like you're trying to use a pip VCS-style requirement?" in str(exc.value)


def test_parse_requirements_file() -> None:
    content = dedent(
        """\
        # Comment.
        --find-links=https://duckduckgo.com
        ansicolors>=1.18.0
        Django==3.2 ; python_version>'3'
        Un-Normalized-PROJECT  # Inline comment.
        pip@ git+https://github.com/pypa/pip.git
        """
    )
    assert set(parse_requirements_file(content, rel_path="foo.txt")) == {
        Requirement.parse("ansicolors>=1.18.0"),
        Requirement.parse("Django==3.2 ; python_version>'3'"),
        Requirement.parse("Un-Normalized-PROJECT"),
        Requirement.parse("pip@ git+https://github.com/pypa/pip.git"),
    }


def test_python_distribution_dependency_injection() -> None:
    rule_runner = RuleRunner(
        rules=[
            inject_python_distribution_dependencies,
            QueryRule(InjectedDependencies, [InjectPythonDistributionDependencies]),
        ],
        target_types=[PythonDistribution, PexBinary],
        objects={"setup_py": PythonArtifact},
    )
    rule_runner.add_to_build_file(
        "project",
        dedent(
            """\
            pex_binary(name="my_binary")
            python_distribution(
                name="dist",
                provides=setup_py(
                    name='my-dist'
                ).with_binaries({"my_cmd": ":my_binary"})
            )
            """
        ),
    )
    tgt = rule_runner.get_target(Address("project", target_name="dist"))
    injected = rule_runner.request(
        InjectedDependencies,
        [InjectPythonDistributionDependencies(tgt[PythonDistributionDependencies])],
    )
    assert injected == InjectedDependencies([Address("project", target_name="my_binary")])


@pytest.mark.parametrize(
    ["raw_value", "expected"],
    (
        (None, {}),
        ({"new_dist": ["new_module"]}, {"new_dist": ("new_module",)}),
        ({"PyYAML": ["custom_yaml"]}, {"PyYAML": ("custom_yaml",)}),
    ),
)
def test_module_mapping_field(
    raw_value: Optional[Dict[str, Iterable[str]]], expected: Dict[str, Tuple[str]]
) -> None:
    merged = dict(DEFAULT_MODULE_MAPPING)
    merged.update(expected)
    actual_value = ModuleMappingField(raw_value, address=Address("", target_name="tests")).value
    assert actual_value == FrozenDict(merged)
