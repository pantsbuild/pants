# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import namedtuple

import pytest

from pants.core.target_types import GenericTarget
from pants.engine.internals.defaults import BuildFileDefaults, BuildFileDefaultsProvider
from pants.engine.target import InvalidFieldException, RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.testutil.pytest_util import no_exception
from pants.util.frozendict import FrozenDict


class Test1Target(GenericTarget):
    alias = "test_type_1"


class Test2Target(GenericTarget):
    alias = "test_type_2"


@pytest.fixture
def provider() -> BuildFileDefaultsProvider:
    return BuildFileDefaultsProvider(
        RegisteredTargetTypes(
            {tgt.alias: tgt for tgt in (GenericTarget, Test1Target, Test2Target)}
        ),
        UnionMembership({}),
    )


def test_assumptions(provider: BuildFileDefaultsProvider) -> None:
    defaults = provider.get_parser_defaults("", BuildFileDefaults({}))
    assert defaults.provider is provider

    defaults.set_defaults({"target": dict(tags=["foo", "bar"])})

    freezed = defaults.freezed_defaults()
    assert freezed == BuildFileDefaults(
        {
            "target": FrozenDict({"tags": ("foo", "bar")}),
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
                    "test_type_1": {
                        "tags": ("tagged-1",),
                    },
                },
                expected_defaults={
                    "target": {
                        "tags": ("tagged-2",),
                    },
                    "test_type_1": {
                        "tags": ("tagged-2",),
                    },
                    "test_type_2": {
                        "tags": ("tagged-2",),
                    },
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
                    "target": {"tags": ("root-tag",)},
                    "test_type_1": {"tags": ("root-tag",)},
                    "test_type_2": {
                        "tags": ("root-tag",),
                        "description": "extend default with desc",
                    },
                },
                expected_defaults={
                    "target": {"tags": ("root-tag",)},
                    "test_type_1": {"tags": ("root-tag",)},
                    "test_type_2": {"description": "only desc default"},
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
                args=({"test_type_1": ()},),
                expected_error=pytest.raises(
                    ValueError,
                    match=(
                        r"Invalid default field values in //#__defaults__ for target type "
                        r"test_type_1, must be an `dict` but was \(\) with type `tuple`\."
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
                parent_defaults={"test_type_1": {"tags": ("foo-bar",)}},
                expected_defaults={},
            ),
            id="reset default",
        ),
    ],
)
def test_set_defaults(provider: BuildFileDefaultsProvider, scenario: Scenario) -> None:
    with (scenario.expected_error or no_exception()):
        defaults = provider.get_parser_defaults(
            scenario.path,
            BuildFileDefaults(
                {tgt: FrozenDict(val) for tgt, val in scenario.parent_defaults.items()}
            ),
        )
        defaults.set_defaults(*scenario.args, **scenario.kwargs)
        actual_defaults = {
            tgt: dict(field_values) for tgt, field_values in defaults.freezed_defaults().items()
        }
        assert scenario.expected_defaults == actual_defaults
