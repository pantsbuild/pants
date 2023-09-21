# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from typing import Iterable

import toml

from pants.backend.javascript.subsystems import nodejs_tool
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolRequest
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonResolveField,
    PythonSourceField,
)
from pants.backend.python.typecheck.pyright.skip_field import SkipPyrightField
from pants.backend.python.typecheck.pyright.subsystem import Pyright
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.partition import (
    _partition_by_interpreter_constraints_and_resolve,
)
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.util_rules import config_files
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.collection import Collection
from pants.engine.fs import CreateDigest, DigestContents, FileContent
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import MultiGet
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.target import CoarsenedTargets, CoarsenedTargetsRequest, FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PyrightFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    sources: PythonSourceField
    resolve: PythonResolveField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPyrightField).value


class PyrightRequest(CheckRequest):
    field_set_type = PyrightFieldSet
    tool_name = Pyright.options_scope


@dataclass(frozen=True)
class PyrightPartition:
    field_sets: FrozenOrderedSet[PyrightFieldSet]
    root_targets: CoarsenedTargets
    resolve_description: str | None
    interpreter_constraints: InterpreterConstraints

    def description(self) -> str:
        ics = str(sorted(str(c) for c in self.interpreter_constraints))
        return f"{self.resolve_description}, {ics}" if self.resolve_description else ics


class PyrightPartitions(Collection[PyrightPartition]):
    pass


async def _patch_config_file(
    config_files: ConfigFiles, venv_dir: str, source_roots: Iterable[str]
) -> Digest:
    """Patch the Pyright config file to use the incoming venv directory (from
    requirements_venv_pex). If there is no config file, create a dummy pyrightconfig.json with the
    `venv` key populated.

    The incoming venv directory works alongside the `--venvpath` CLI argument.

    Additionally, add source roots to the `extraPaths` key in the config file.
    """

    source_roots_list = list(source_roots)
    if not config_files.snapshot.files:
        # venv workaround as per: https://github.com/microsoft/pyright/issues/4051
        generated_config = {"venv": venv_dir, "extraPaths": source_roots_list}
        return await Get(
            Digest,
            CreateDigest(
                [
                    FileContent(
                        "pyrightconfig.json",
                        json.dumps(generated_config).encode(),
                    )
                ]
            ),
        )

    config_contents = await Get(DigestContents, Digest, config_files.snapshot.digest)
    new_files: list[FileContent] = []
    for file in config_contents:
        # This only supports a single json config file in the root of the project
        # https://github.com/pantsbuild/pants/issues/17816 tracks supporting multiple config files and workspaces
        if file.path == "pyrightconfig.json":
            json_config = json.loads(file.content)
            json_config["venv"] = venv_dir
            json_extra_paths: list[str] = json_config.get("extraPaths", [])
            json_config["extraPaths"] = list(OrderedSet(json_extra_paths + source_roots_list))
            new_content = json.dumps(json_config).encode()
            new_files.append(replace(file, content=new_content))

        # This only supports a single pyproject.toml file in the root of the project
        # https://github.com/pantsbuild/pants/issues/17816 tracks supporting multiple config files and workspaces
        elif file.path == "pyproject.toml":
            toml_config = toml.loads(file.content.decode())
            pyright_config = toml_config["tool"]["pyright"]
            pyright_config["venv"] = venv_dir
            toml_extra_paths: list[str] = pyright_config.get("extraPaths", [])
            pyright_config["extraPaths"] = list(OrderedSet(toml_extra_paths + source_roots_list))
            new_content = toml.dumps(toml_config).encode()
            new_files.append(replace(file, content=new_content))

    return await Get(Digest, CreateDigest(new_files))


@rule(
    desc="Pyright typecheck each partition based on its interpreter_constraints",
    level=LogLevel.DEBUG,
)
async def pyright_typecheck_partition(
    partition: PyrightPartition,
    pyright: Pyright,
    pex_environment: PexEnvironment,
) -> CheckResult:
    root_sources_get = Get(
        SourceFiles,
        SourceFilesRequest(fs.sources for fs in partition.field_sets),
    )

    # Grab the closure of the root source files to be typechecked
    transitive_sources_get = Get(
        PythonSourceFiles, PythonSourceFilesRequest(partition.root_targets.closure())
    )

    # See `requirements_venv_pex` for how this will get wrapped in a `VenvPex`.
    requirements_pex_get = Get(
        Pex,
        RequirementsPexRequest(
            (fs.address for fs in partition.field_sets),
            hardcoded_interpreter_constraints=partition.interpreter_constraints,
        ),
    )

    # Look for any/all of the Pyright configuration files (the config is modified below
    # for the `venv` workaround)
    config_files_get = Get(
        ConfigFiles,
        ConfigFilesRequest,
        pyright.config_request(),
    )

    root_sources, transitive_sources, requirements_pex, config_files = await MultiGet(
        root_sources_get,
        transitive_sources_get,
        requirements_pex_get,
        config_files_get,
    )

    requirements_venv_pex = await Get(
        VenvPex,
        PexRequest(
            output_filename="requirements_venv.pex",
            internal_only=True,
            pex_path=[requirements_pex],
            interpreter_constraints=partition.interpreter_constraints,
        ),
    )

    # Force the requirements venv to materialize always by running a no-op.
    # This operation must be called with `ProcessCacheScope.SESSION`
    # as the venv is cached per session.
    await Get(
        ProcessResult,
        VenvPexProcess(
            requirements_venv_pex,
            description="Force venv to materialize",
            argv=["-c", "''"],
            cache_scope=ProcessCacheScope.SESSION,
        ),
    )

    # Patch the config file to use the venv directory from the requirements pex,
    # and add source roots to the `extraPaths` key in the config file.
    patched_config_digest = await _patch_config_file(
        config_files, requirements_venv_pex.venv_rel_dir, transitive_sources.source_roots
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                transitive_sources.source_files.snapshot.digest,
                requirements_venv_pex.digest,
                patched_config_digest,
            ]
        ),
    )

    complete_pex_env = pex_environment.in_workspace()
    process = await Get(
        Process,
        NodeJSToolRequest,
        pyright.request(
            args=(
                f"--venvpath={complete_pex_env.pex_root}",  # Used with `venv` in config
                *pyright.args,  # User-added arguments
                *(os.path.join("{chroot}", file) for file in root_sources.snapshot.files),
            ),
            input_digest=input_digest,
            description=f"Run Pyright on {pluralize(len(root_sources.snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    result = await Get(FallibleProcessResult, Process, process)
    return CheckResult.from_fallible_process_result(
        result,
        partition_description=partition.description(),
    )


@rule(
    desc="Determine if it is necessary to partition Pyright's input (interpreter_constraints and resolves)",
    level=LogLevel.DEBUG,
)
async def pyright_determine_partitions(
    request: PyrightRequest,
    pyright: Pyright,
    python_setup: PythonSetup,
) -> PyrightPartitions:
    resolve_and_interpreter_constraints_to_field_sets = (
        _partition_by_interpreter_constraints_and_resolve(request.field_sets, python_setup)
    )

    coarsened_targets = await Get(
        CoarsenedTargets,
        CoarsenedTargetsRequest(field_set.address for field_set in request.field_sets),
    )
    coarsened_targets_by_address = coarsened_targets.by_address()

    return PyrightPartitions(
        PyrightPartition(
            FrozenOrderedSet(field_sets),
            CoarsenedTargets(
                OrderedSet(
                    coarsened_targets_by_address[field_set.address] for field_set in field_sets
                )
            ),
            resolve if len(python_setup.resolves) > 1 else None,
            interpreter_constraints or pyright.interpreter_constraints,
        )
        for (resolve, interpreter_constraints), field_sets in sorted(
            resolve_and_interpreter_constraints_to_field_sets.items()
        )
    )


@rule(desc="Typecheck using Pyright", level=LogLevel.DEBUG)
async def pyright_typecheck(
    request: PyrightRequest,
    pyright: Pyright,
) -> CheckResults:
    if pyright.skip:
        return CheckResults([], checker_name=request.tool_name)

    partitions = await Get(PyrightPartitions, PyrightRequest, request)
    partitioned_results = await MultiGet(
        Get(CheckResult, PyrightPartition, partition) for partition in partitions
    )
    return CheckResults(
        partitioned_results,
        checker_name=request.tool_name,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *config_files.rules(),
        *pex_from_targets.rules(),
        *nodejs_tool.rules(),
        UnionRule(CheckRequest, PyrightRequest),
    )
