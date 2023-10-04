# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.target_types import PythonDistribution
from pants.backend.python.typecheck.mypy.subsystem import (
    MyPy,
    MyPyConfigFile,
    MyPyFirstPartyPlugins,
)
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.package_dists import (
    DistBuildEnvironment,
    DistBuildEnvironmentRequest,
)
from pants.backend.python.util_rules.pex import Pex, PexRequest
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import BoolField, Target
from pants.engine.unions import UnionRule
from pants.util.strutil import help_text


class UsesMyPycField(BoolField):
    alias = "uses_mypyc"
    default = False
    help = help_text(
        """
        If true, this distribution is built using mypyc.

        In this case, Pants will build the distribution in an environment that includes
        mypy, as configured in the `[mypy]` subsystem, including plugins, config files,
        extra type stubs, and the distribution's own requirements (which normally would not
        be needed at build time, but in this case may provide necessary type annotations).

        You will typically set this field on distributions whose `setup.py` uses
        `mypyc.build.mypycify()`. See https://mypyc.readthedocs.io/en/latest/index.html .
        """
    )


@dataclass(frozen=True)
class MyPycDistBuildEnvironmentRequest(DistBuildEnvironmentRequest):
    @classmethod
    def is_applicable(cls, tgt: Target) -> bool:
        return tgt.get(UsesMyPycField).value


@rule(desc="Get mypyc build environment")
async def get_mypyc_build_environment(
    request: MyPycDistBuildEnvironmentRequest,
    first_party_plugins: MyPyFirstPartyPlugins,
    mypy_config_file: MyPyConfigFile,
    mypy: MyPy,
) -> DistBuildEnvironment:
    mypy_pex_get = Get(
        Pex,
        PexRequest,
        mypy.to_pex_request(
            interpreter_constraints=request.interpreter_constraints,
            extra_requirements=first_party_plugins.requirement_strings,
        ),
    )
    requirements_pex_get = Get(
        Pex,
        RequirementsPexRequest(
            addresses=request.target_addresses,
            hardcoded_interpreter_constraints=request.interpreter_constraints,
        ),
    )
    mypy_pex, requirements_pex = await MultiGet(mypy_pex_get, requirements_pex_get)
    return DistBuildEnvironment(
        extra_build_time_requirements=(mypy_pex, requirements_pex),
        extra_build_time_inputs=mypy_config_file.digest,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(DistBuildEnvironmentRequest, MyPycDistBuildEnvironmentRequest),
        PythonDistribution.register_plugin_field(UsesMyPycField),
        *pex_from_targets.rules(),
    ]
