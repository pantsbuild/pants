# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import namedtuple

import pytest

from pants.core.target_types import GenericTarget
from pants.engine.internals.defaults import BuildFileDefaultsProvider
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
    mutable = provider.get_defaults_for("test").as_mutable()
    assert mutable.provider is provider

    mutable.set_defaults({"target": dict(tags=["foo", "bar"])})
    assert set(provider.defaults.keys()) == {"", "test"}
    assert provider.defaults["test"].defaults == FrozenDict({})

    mutable.commit()
    assert set(provider.defaults.keys()) == {"", "test"}
    assert provider.defaults["test"].defaults == FrozenDict(
        {
            "target": FrozenDict({"tags": ("foo", "bar")}),
        }
    )


Step = namedtuple("Step", "path, args, kwargs, defaults, error", defaults=("", (), {}, {}, None))


@pytest.mark.parametrize(
    "scenario_steps",
    [
        pytest.param(
            (
                Step(
                    path="src/proj",
                    args=({Test1Target.alias: dict(tags=["tagged-1"])},),
                    defaults={
                        "": {},
                        "src": {},
                        "src/proj": {
                            "test_type_1": {
                                "tags": ("tagged-1",),
                            },
                        },
                    },
                ),
                Step(
                    path="src/proj/a",
                    kwargs=dict(all=dict(tags=["tagged-2"])),
                    defaults={
                        "": {},
                        "src": {},
                        "src/proj": {
                            "test_type_1": {
                                "tags": ("tagged-1",),
                            },
                        },
                        "src/proj/a": {
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
                    },
                ),
            ),
            id="simple inherit",
        ),
        pytest.param(
            (
                Step(
                    path="src/proj/a",
                    args=({Test1Target.alias: dict(tags=["tagged-1"])},),
                    defaults={
                        "": {},
                        "src": {},
                        "src/proj": {},
                        "src/proj/a": {
                            "test_type_1": {
                                "tags": ("tagged-1",),
                            },
                        },
                    },
                ),
                Step(
                    path="src/proj",
                    kwargs=dict(all=dict(tags=["tagged-2"])),
                    defaults={
                        "": {},
                        "src": {},
                        "src/proj": {
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
                        "src/proj/a": {
                            "test_type_1": {
                                "tags": ("tagged-1",),
                            },
                        },
                    },
                ),
            ),
            id="backwards updates does not cascade",
        ),
        pytest.param(
            (
                Step(
                    path="",
                    kwargs=dict(all=dict(tags=["root-tag"])),
                    defaults={
                        "": {
                            "target": {"tags": ("root-tag",)},
                            "test_type_1": {"tags": ("root-tag",)},
                            "test_type_2": {"tags": ("root-tag",)},
                        },
                    },
                ),
                Step(
                    path="src",
                    args=({Test2Target.alias: dict(description="extend default with desc")},),
                    kwargs=dict(extend=True),
                    defaults={
                        "": {
                            "target": {"tags": ("root-tag",)},
                            "test_type_1": {"tags": ("root-tag",)},
                            "test_type_2": {"tags": ("root-tag",)},
                        },
                        "src": {
                            "target": {"tags": ("root-tag",)},
                            "test_type_1": {"tags": ("root-tag",)},
                            "test_type_2": {
                                "tags": ("root-tag",),
                                "description": "extend default with desc",
                            },
                        },
                    },
                ),
                Step(
                    path="src",
                    args=({Test2Target.alias: dict(description="only desc default")},),
                    kwargs=dict(extend=False),
                    defaults={
                        "": {
                            "target": {"tags": ("root-tag",)},
                            "test_type_1": {"tags": ("root-tag",)},
                            "test_type_2": {"tags": ("root-tag",)},
                        },
                        "src": {
                            "target": {"tags": ("root-tag",)},
                            "test_type_1": {"tags": ("root-tag",)},
                            "test_type_2": {"description": "only desc default"},
                        },
                    },
                ),
            ),
            id="extend test",
        ),
        pytest.param(
            (
                Step(
                    args=(["bad type"],),
                    error=pytest.raises(
                        ValueError,
                        match=(
                            r"Expected dictionary mapping targets to default field values for "
                            r"//#__defaults__ but got: list\."
                        ),
                    ),
                ),
            ),
            id="invalid defaults args",
        ),
        pytest.param(
            (
                Step(
                    args=({"test_type_1": ()},),
                    error=pytest.raises(
                        ValueError,
                        match=(
                            r"Invalid default field values in //#__defaults__ for target type "
                            r"test_type_1, must be an `dict` but was \(\) with type `tuple`\."
                        ),
                    ),
                ),
            ),
            id="invalid default field values",
        ),
        pytest.param(
            (
                Step(
                    args=({"unknown_target": {}},),
                    error=pytest.raises(
                        ValueError,
                        match=r"Unrecognized target type unknown_target in //#__defaults__\.",
                    ),
                ),
            ),
            id="unknown target",
        ),
        pytest.param(
            (
                Step(
                    args=({Test1Target.alias: {"does-not-exist": ()}},),
                    error=pytest.raises(
                        InvalidFieldException,
                        match=(
                            r"Unrecognized field `does-not-exist` for target test_type_1\. "
                            r"Valid fields are: dependencies, description, tags\."
                        ),
                    ),
                ),
            ),
            id="invalid field",
        ),
        pytest.param(
            (
                Step(
                    path="src/proj/a",
                    args=({"test_type_1": {"tags": "foo-bar"}},),
                    error=pytest.raises(
                        InvalidFieldException,
                        match=(
                            r"The 'tags' field in target src/proj/a#__defaults__ must be an "
                            r"iterable of strings \(e\.g\. a list of strings\), but was "
                            r"`'foo-bar'` with type `str`\."
                        ),
                    ),
                ),
            ),
            id="invalid field value",
        ),
        pytest.param(
            (
                Step(
                    kwargs=dict(all=dict(foo_bar="ignored")),
                    defaults={"": {}},
                ),
            ),
            id="unknown fields ignored for `all` targets",
        ),
        pytest.param(
            (
                Step(
                    args=({Test1Target.alias: dict(tags=["foo-bar"])},),
                    defaults={
                        "": {"test_type_1": {"tags": ("foo-bar",)}},
                    },
                ),
                Step(
                    args=({Test1Target.alias: {}},),
                    defaults={"": {}},
                ),
            ),
            id="reset default",
        ),
    ],
)
def test_set_defaults(provider: BuildFileDefaultsProvider, scenario_steps: tuple[Step]) -> None:
    for idx, step in enumerate(scenario_steps):
        with (step.error or no_exception()):
            mutable = provider.get_defaults_for(step.path).as_mutable()
            mutable.set_defaults(*step.args, **step.kwargs)
            mutable.commit()
            all_defaults = {
                defaults.path: {
                    tgt: dict(field_values) for tgt, field_values in defaults.defaults.items()
                }
                for defaults in provider.defaults.values()
            }
            assert (
                step.defaults == all_defaults
            ), f"Step {idx+1}/{len(scenario_steps)} - path: {step.path}"
