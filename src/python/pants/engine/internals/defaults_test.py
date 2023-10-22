# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import namedtuple

import pytest

from pants.core.target_types import GenericTarget, GenericTargetDependenciesField
from pants.engine.internals.defaults import (
    BuildFileDefaults,
    BuildFileDefaultsParserState,
    ParametrizeDefault,
    TargetDefaults,
)
from pants.engine.internals.parametrize import Parametrize
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    InvalidFieldException,
    OverridesField,
    RegisteredTargetTypes,
    TargetGenerator,
)
from pants.engine.unions import UnionMembership
from pants.testutil.pytest_util import no_exception
from pants.util.frozendict import FrozenDict


class Test1Target(GenericTarget):
    alias = "test_type_1"


class Test2Target(GenericTarget):
    alias = "test_type_2"


class TestGenTarget(GenericTarget):
    alias = "test_gen"


class TestGenTargetGenerator(TargetGenerator):
    alias = "test_gen_targets"
    generated_target_cls = TestGenTarget
    core_fields = (
        OverridesField,
        *COMMON_TARGET_FIELDS,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (GenericTargetDependenciesField,)


@pytest.fixture
def registered_target_types() -> RegisteredTargetTypes:
    return RegisteredTargetTypes(
        {
            tgt.alias: tgt
            for tgt in (
                GenericTarget,
                Test1Target,
                Test2Target,
                TestGenTarget,
                TestGenTargetGenerator,
            )
        }
    )


@pytest.fixture
def union_membership() -> UnionMembership:
    return UnionMembership({})


def test_assumptions(
    registered_target_types: RegisteredTargetTypes, union_membership: UnionMembership
) -> None:
    defaults = BuildFileDefaultsParserState.create(
        "", BuildFileDefaults({}), registered_target_types, union_membership
    )
    defaults.set_defaults({"target": dict(tags=["foo", "bar"])})

    frozen = defaults.get_frozen_defaults()
    assert frozen == BuildFileDefaults(
        {
            "target": TargetDefaults(args=(), kwargs=FrozenDict({"tags": ("foo", "bar")})),
        }
    )


Scenario = namedtuple(
    "Scenario",
    "path, args, kwargs, expected_defaults, expected_error, parent_defaults",
    defaults=("", (), {}, {}, None, {}),
)


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(
            Scenario(
                path="src/proj/a",
                kwargs=dict(all=dict(tags=["tagged-2"])),
                parent_defaults={
                    "test_type_1": ((), {"tags": ("tagged-1",)}),
                },
                expected_defaults={
                    "target": ((), {"tags": ("tagged-2",)}),
                    "test_type_1": ((), {"tags": ("tagged-2",)}),
                    "test_type_2": ((), {"tags": ("tagged-2",)}),
                    "test_gen": ((), {"tags": ("tagged-2",)}),
                    "test_gen_targets": ((), {"tags": ("tagged-2",)}),
                },
            ),
            id="simple inherit",
        ),
        pytest.param(
            Scenario(
                path="src",
                args=({Test2Target.alias: dict(description="only desc default")},),
                kwargs=dict(extend=False),
                parent_defaults={
                    "target": ((), {"tags": ("root-tag",)}),
                    "test_type_1": ((), {"tags": ("root-tag",)}),
                    "test_type_2": (
                        (),
                        {"tags": ("root-tag",), "description": "extend default with desc"},
                    ),
                },
                expected_defaults={
                    "target": ((), {"tags": ("root-tag",)}),
                    "test_type_1": ((), {"tags": ("root-tag",)}),
                    "test_type_2": ((), {"description": "only desc default"}),
                },
            ),
            id="extend test",
        ),
        pytest.param(
            Scenario(
                args=(["bad type"],),
                expected_error=pytest.raises(
                    ValueError,
                    match=(
                        r"Expected dictionary mapping targets to default field values for "
                        r"//#__defaults__ but got: list\."
                    ),
                ),
            ),
            id="invalid defaults args",
        ),
        pytest.param(
            Scenario(
                args=({"test_type_1": 42},),
                expected_error=pytest.raises(
                    ValueError,
                    match=(
                        r"Invalid default field values in //#__defaults__ for target type "
                        r"test_type_1, must be an `dict` or `list` but was 42 with type `int`\."
                    ),
                ),
            ),
            id="invalid default field values",
        ),
        pytest.param(
            Scenario(
                args=({"unknown_target": {}},),
                expected_error=pytest.raises(
                    ValueError,
                    match=r"Unrecognized target type unknown_target in //#__defaults__\.",
                ),
            ),
            id="unknown target",
        ),
        pytest.param(
            Scenario(
                args=({Test1Target.alias: {"does-not-exist": ()}},),
                expected_error=pytest.raises(
                    InvalidFieldException,
                    match=(
                        r"Unrecognized field `does-not-exist` for target test_type_1\. "
                        r"Valid fields are: dependencies, description, tags\."
                    ),
                ),
            ),
            id="invalid field",
        ),
        pytest.param(
            Scenario(
                path="src/proj/a",
                args=({"test_type_1": {"tags": "foo-bar"}},),
                expected_error=pytest.raises(
                    InvalidFieldException,
                    match=(
                        r"The 'tags' field in target src/proj/a#__defaults__ must be an "
                        r"iterable of strings \(e\.g\. a list of strings\), but was "
                        r"`'foo-bar'` with type `str`\."
                    ),
                ),
            ),
            id="invalid field value",
        ),
        pytest.param(
            Scenario(
                kwargs=dict(all=dict(foo_bar="ignored")),
                expected_defaults={},
            ),
            id="unknown fields ignored for `all` targets",
        ),
        pytest.param(
            Scenario(
                args=({Test1Target.alias: {}},),
                parent_defaults={"test_type_1": ((), {"tags": ("foo-bar",)})},
                expected_defaults={},
            ),
            id="reset default",
        ),
        pytest.param(
            Scenario(
                args=({TestGenTargetGenerator.alias: {Dependencies.alias: ["some/dep"]}},),
                expected_defaults={"test_gen_targets": ((), {"dependencies": ("some/dep",)})},
            ),
            id="default value for moved field",
        ),
        pytest.param(
            Scenario(
                args=({Test1Target.alias: {"tags": Parametrize(["foo"], ["bar"], baz=["baz"])}},),
                expected_defaults={
                    "test_type_1": (
                        (),
                        {
                            "tags": ParametrizeDefault(("foo",), ("bar",), baz=("baz",)),
                        },
                    )
                },
            ),
            id="parametrize default field value",
        ),
        pytest.param(
            Scenario(
                args=(
                    {
                        ("test_gen_targets",): dict(
                            overrides={"*_generated.py": {"skip_yapf": True}}
                        )
                    },
                ),
                expected_defaults={
                    "test_gen_targets": (
                        (),
                        dict(
                            overrides=FrozenDict.deep_freeze(
                                {("*_generated.py",): {"skip_yapf": True}}
                            )
                        ),
                    ),
                },
            ),
            id="overrides value not frozen (issue #18784)",
        ),
        pytest.param(
            Scenario(
                args=({Test1Target.alias: ["arg1", "arg2"]},),
                expected_defaults={"test_type_1": (("arg1", "arg2"), {})},
            ),
            id="default parametrization groups",
        ),
    ],
)
def test_set_defaults(
    scenario: Scenario,
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
) -> None:
    with scenario.expected_error or no_exception():
        defaults = BuildFileDefaultsParserState.create(
            scenario.path,
            BuildFileDefaults(
                {
                    tgt: TargetDefaults(args=args, kwargs=FrozenDict(kwargs))
                    for tgt, (args, kwargs) in scenario.parent_defaults.items()
                }
            ),
            registered_target_types,
            union_membership,
        )
        defaults.set_defaults(*scenario.args, **scenario.kwargs)
        actual_defaults = {
            tgt_alias: (tgt_defaults.args, dict(tgt_defaults.kwargs))
            for tgt_alias, tgt_defaults in defaults.get_frozen_defaults().items()
        }
        assert scenario.expected_defaults == actual_defaults
