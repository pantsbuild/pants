# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Tuple

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.dependency_inference.module_mapper import (
    ResolveName,
    ThirdPartyPythonModuleMapping,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    EntryPoint,
    PythonRequirementDependenciesField,
    PythonRequirementModulesField,
    PythonRequirementResolveField,
    PythonRequirementsField,
    PythonRequirementTypeStubModulesField,
)
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexRequest
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.build_graph.address import Address
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized

logger = logging.getLogger(__name__)


def _in_chroot(relpath: str) -> str:
    return os.path.join("{chroot}", relpath)


@dataclass(frozen=True)
class PythonRequirementFieldSet(RunFieldSet):
    supports_debug_adapter = False
    required_fields = (
        PythonRequirementsField,
        PythonRequirementDependenciesField,
        PythonRequirementModulesField,
        PythonRequirementTypeStubModulesField,
        PythonRequirementResolveField,
    )
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    requirements: PythonRequirementsField
    dependencies: PythonRequirementDependenciesField
    modules: PythonRequirementModulesField
    resolve: PythonRequirementResolveField

    def __repr__(self):
        return f"PythonRequirementFieldSet({self.requirements.value=}, {self.dependencies.value=}, {self.modules.value=})"


@memoized
def _invert_module_mapping(
    resolve: ResolveName, module_mapping: ThirdPartyPythonModuleMapping
) -> FrozenDict[Address, Tuple[str, ...]]:
    """Provide an inverted module mapping that can specify the set of modules known to be fulfilled
    by a given target address."""
    d: dict[Address, list[str]] = defaultdict(list)
    for module_name, providers in module_mapping.resolves_to_modules_to_providers[resolve].items():
        for provider in providers:
            d[provider.addr].append(module_name)

    return FrozenDict((address, tuple(modules)) for address, modules in d.items())


@rule(level=LogLevel.DEBUG)
async def create_python_requirement_run_request(
    field_set: PythonRequirementFieldSet,
    pex_env: PexEnvironment,
    python_setup: PythonSetup,
    module_mapping: ThirdPartyPythonModuleMapping,
) -> RunRequest:

    addresses = [field_set.address]
    # TODO: add support for entry point field.

    logger.warning(f"{field_set=}")

    resolve = field_set.resolve.value
    if not resolve:
        resolve = python_setup.default_resolve

    modules_for_address = _invert_module_mapping(resolve, module_mapping)
    logger.warning(modules_for_address)

    modules = field_set.modules.value
    reqs = field_set.requirements.value

    if modules and len(modules) == 1:
        # Modules specified in the `BUILD` file
        entry_point_module = modules[0]
    elif len(modules_for_address[field_set.address]) == 1:
        # Check the third-party module mapping
        entry_point_module = modules_for_address[field_set.address][0]
    elif len(reqs) == 1:
        # Use the canonicalized project name for a single-requirement target
        entry_point_module = canonicalize_project_name(reqs[0].project_name)
    else:
        raise Exception(
            "Requirement must provide a single module, specify a single requirement, or specify "
            "an `entry_point`"
        )

    pex_request = await Get(
        PexRequest,
        PexFromTargetsRequest(
            addresses,
            output_filename=f"{entry_point_module}.pex",
            internal_only=True,
            include_source_files=False,
            include_local_dists=True,
            # `PEX_EXTRA_SYS_PATH` should contain this entry_point's module.
            main=EntryPoint(entry_point_module),
            additional_args=(
                # N.B.: Since we cobble together the runtime environment via PEX_EXTRA_SYS_PATH
                # below, it's important for any app that re-executes itself that these environment
                # variables are not stripped.
                "--no-strip-pex-env",
            ),
        ),
    )

    complete_pex_environment = pex_env.in_sandbox(working_directory=None)
    venv_pex = await Get(VenvPex, VenvPexRequest(pex_request, complete_pex_environment))
    input_digest = venv_pex.digest

    extra_env = {
        **complete_pex_environment.environment_dict(python_configured=venv_pex.python is not None),
    }

    return RunRequest(
        digest=input_digest,
        args=[_in_chroot(venv_pex.pex.argv0)],
        extra_env=extra_env,
        append_only_caches=complete_pex_environment.append_only_caches,
    )


def rules():
    return [
        *collect_rules(),
        *PythonRequirementFieldSet.rules(),
    ]
