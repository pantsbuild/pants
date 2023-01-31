# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.framework.stevedore.setup_py_kwargs import (
    StevedoreSetupKwargs,
    StevedoreSetupKwargsRequest,
)
from pants.backend.python.framework.stevedore.setup_py_kwargs import (
    rules as stevedore_setup_py_rules,
)
from pants.backend.python.framework.stevedore.target_types import StevedoreExtension
from pants.backend.python.framework.stevedore.target_types_rules import (
    rules as stevedore_target_types_rules,
)
from pants.backend.python.goals.setup_py import SetupKwargs, SetupKwargsRequest
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.target_types import (
    PythonDistribution,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
)
from pants.backend.python.target_types_rules import rules as python_target_types_rules
from pants.engine.addresses import Address
from pants.engine.rules import rule
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict


class DummySetupKwargsRequest(SetupKwargsRequest):
    @classmethod
    def is_applicable(cls, _: Target) -> bool:
        return True


@rule
async def dummy_setup_kwargs_plugin(request: DummySetupKwargsRequest) -> SetupKwargs:
    return SetupKwargs(request.explicit_kwargs, address=request.target.address)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *python_target_types_rules(),
            *stevedore_target_types_rules(),
            *stevedore_setup_py_rules(),
            dummy_setup_kwargs_plugin,
            QueryRule(StevedoreSetupKwargs, (StevedoreSetupKwargsRequest,)),
        ],
        target_types=[
            PythonDistribution,
            PythonSourceTarget,
            PythonSourcesGeneratorTarget,
            StevedoreExtension,
        ],
        objects={"python_artifact": PythonArtifact},
    )
    rule_runner.write_files(
        {
            "runners/foobar_runner/BUILD": dedent(
                """\
                stevedore_extension(
                    name="runner",
                    namespace="st2common.runners.runner",
                    entry_points={
                        "foobar": "foobar_runner.foobar_runner",
                    },
                )
                stevedore_extension(
                    name="thing",
                    namespace="some.thing.else",
                    entry_points={
                        "thing2": "foobar_runner.thing2",
                        "thing1": "foobar_runner.thing1",
                    },
                )
                python_distribution(
                    provides=python_artifact(
                        name="stackstorm-runner-foobar",
                    ),
                    dependencies=["./foobar_runner"],
                )
                """
            ),
            "runners/foobar_runner/foobar_runner/BUILD": "python_sources()",
            "runners/foobar_runner/foobar_runner/__init__.py": "",
            "runners/foobar_runner/foobar_runner/foobar_runner.py": "",
            "runners/foobar_runner/foobar_runner/thing1.py": "",
            "runners/foobar_runner/foobar_runner/thing2.py": "",
        }
    )
    args = [
        "--source-root-patterns=runners/*_runner",
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


def test_stevedore_kwargs_for_setup_py(rule_runner: RuleRunner) -> None:
    def gen_setup_kwargs(address: Address) -> StevedoreSetupKwargs:
        target = rule_runner.get_target(address)
        return rule_runner.request(
            StevedoreSetupKwargs,
            [StevedoreSetupKwargsRequest(DummySetupKwargsRequest(target))],
        )

    assert gen_setup_kwargs(Address("runners/foobar_runner")) == StevedoreSetupKwargs(
        FrozenDict(
            {
                "entry_points": FrozenDict(
                    {
                        # this should be sorted
                        "some.thing.else": (
                            "thing1 = foobar_runner.thing1",
                            "thing2 = foobar_runner.thing2",
                        ),
                        "st2common.runners.runner": ("foobar = foobar_runner.foobar_runner",),
                    }
                )
            }
        )
    )
