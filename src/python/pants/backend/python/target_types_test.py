# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Optional

import pytest
from pkg_resources import Requirement

from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.target_types import (
    InjectPythonDistributionDependencies,
    PexBinary,
    PexBinarySources,
    PexEntryPointField,
    PythonDistribution,
    PythonDistributionDependencies,
    PythonRequirementsField,
    PythonTestsTimeout,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
    resolve_pex_entry_point,
)
from pants.backend.python.target_types import rules as target_type_rules
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import (
    InjectedDependencies,
    InvalidFieldException,
    InvalidFieldTypeException,
)
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import QueryRule, RuleRunner


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


def test_resolve_pex_binary_entry_point() -> None:
    rule_runner = RuleRunner(
        rules=[
            resolve_pex_entry_point,
            QueryRule(ResolvedPexEntryPoint, [ResolvePexEntryPointRequest]),
        ]
    )

    def assert_resolved(
        *, entry_point: Optional[str], source: Optional[str], expected: Optional[str]
    ) -> None:
        addr = Address("src/python/project")
        rule_runner.create_file("src/python/project/app.py")
        ep_field = PexEntryPointField(entry_point, address=addr)
        sources = PexBinarySources([source] if source else None, address=addr)
        result = rule_runner.request(
            ResolvedPexEntryPoint, [ResolvePexEntryPointRequest(ep_field, sources)]
        )
        assert result.val == expected

    assert_resolved(
        entry_point="custom.entry_point:func", source="app.py", expected="custom.entry_point:func"
    )
    assert_resolved(entry_point=":func", source="app.py", expected="project.app:func")
    assert_resolved(entry_point=None, source="app.py", expected="project.app")

    # We special case the strings `<none>` and `<None>`.
    assert_resolved(entry_point="<none>", source=None, expected=None)
    assert_resolved(entry_point="<none>", source="app.py", expected=None)
    assert_resolved(entry_point="<None>", source=None, expected=None)
    assert_resolved(entry_point="<None>", source="app.py", expected=None)

    with pytest.raises(ExecutionError):
        assert_resolved(entry_point=":func", source=None, expected="doesnt matter")


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


def test_python_distribution_dependency_injection() -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_type_rules(),
            QueryRule(
                InjectedDependencies,
                (InjectPythonDistributionDependencies,),
            ),
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
