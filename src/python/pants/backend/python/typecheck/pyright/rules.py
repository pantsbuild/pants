# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import json
import logging
import os
import shlex
from collections.abc import Iterable
from dataclasses import dataclass, replace

import toml

from pants.backend.javascript.subsystems import nodejs_tool
from pants.backend.javascript.subsystems.nodejs import NodeJS
from pants.backend.javascript.subsystems.nodejs_tool import prepare_tool_process
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
from pants.backend.python.util_rules.pex import (
    PexRequest,
    VenvPexProcess,
    VenvPexRequest,
    create_pex,
    create_venv_pex,
)
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFilesRequest,
    prepare_python_sources,
)
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults, CheckSubsystem
from pants.core.util_rules import config_files
from pants.core.util_rules.config_files import ConfigFiles, find_config_file
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.core.util_rules.system_binaries import CatBinary, ShBinary
from pants.engine.collection import Collection
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.graph import resolve_coarsened_targets as coarsened_targets_get
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import (
    create_digest,
    execute_process,
    get_digest_contents,
    merge_digests,
)
from pants.engine.process import ProcessCacheScope, execute_process_or_raise
from pants.engine.rules import Rule, collect_rules, implicitly, rule
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
        generated_config: dict[str, str | list[str]] = {
            "venv": venv_dir,
            "extraPaths": source_roots_list,
        }
        return await create_digest(
            CreateDigest(
                [
                    FileContent(
                        "pyrightconfig.json",
                        json.dumps(generated_config).encode(),
                    )
                ]
            )
        )

    config_contents = await get_digest_contents(config_files.snapshot.digest)
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

    return await create_digest(CreateDigest(new_files))


@rule(
    desc="Pyright typecheck each partition based on its interpreter_constraints",
    level=LogLevel.DEBUG,
)
async def pyright_typecheck_partition(
    partition: PyrightPartition,
    pyright: Pyright,
    check_subsystem: CheckSubsystem,
    pex_environment: PexEnvironment,
    nodejs: NodeJS,
    sh_binary: ShBinary,
    cat_binary: CatBinary,
) -> CheckResult:
    root_sources_get = determine_source_files(
        SourceFilesRequest(fs.sources for fs in partition.field_sets)
    )

    # Grab the closure of the root source files to be typechecked
    transitive_sources_get = prepare_python_sources(
        PythonSourceFilesRequest(partition.root_targets.closure()), **implicitly()
    )

    # See `requirements_venv_pex` for how this will get wrapped in a `VenvPex`.
    requirements_pex_get = create_pex(
        **implicitly(
            RequirementsPexRequest(
                (fs.address for fs in partition.field_sets),
                hardcoded_interpreter_constraints=partition.interpreter_constraints,
            )
        )
    )

    # Look for any/all of the Pyright configuration files (the config is modified below
    # for the `venv` workaround)
    config_files_get = find_config_file(pyright.config_request())

    root_sources, transitive_sources, requirements_pex, config_files = await concurrently(
        root_sources_get,
        transitive_sources_get,
        requirements_pex_get,
        config_files_get,
    )

    # This is a workaround for https://github.com/pantsbuild/pants/issues/19946.
    # complete_pex_env needs to be created here so that the test `test_passing_cache_clear`
    # test can pass using the appropriate caching directory.
    # See https://github.com/pantsbuild/pants/pull/19430#discussion_r1337851780
    # for more discussion.
    complete_pex_env = pex_environment.in_workspace()
    requirements_pex_request = PexRequest(
        output_filename="requirements_venv.pex",
        internal_only=True,
        pex_path=[requirements_pex],
        interpreter_constraints=partition.interpreter_constraints,
    )
    requirements_venv_pex = await create_venv_pex(
        VenvPexRequest(requirements_pex_request, complete_pex_env), **implicitly()
    )

    # Force the requirements venv to materialize always by running a no-op.
    # This operation must be called with `ProcessCacheScope.SESSION`
    # so that it runs every time.
    _ = await execute_process_or_raise(
        **implicitly(
            VenvPexProcess(
                requirements_venv_pex,
                description="Force venv to materialize",
                argv=["-c", "''"],
                cache_scope=ProcessCacheScope.PER_SESSION,
            )
        )
    )

    # Patch the config file to use the venv directory from the requirements pex,
    # and add source roots to the `extraPaths` key in the config file.
    patched_config_digest = await _patch_config_file(
        config_files, requirements_venv_pex.venv_rel_dir, transitive_sources.source_roots
    )

    # Prepare the process with as much information as we currently have. This will give us the
    # process's cwd, which we need in order to calculate the relative paths to the input files.
    # We will then manually tweak the argv before actually running.
    input_digest = await merge_digests(
        MergeDigests(
            [
                transitive_sources.source_files.snapshot.digest,
                requirements_venv_pex.digest,
                patched_config_digest,
            ]
        )
    )
    process = await prepare_tool_process(
        pyright.request(
            args=(
                f"--venvpath={complete_pex_env.pex_root}",  # Used with `venv` in config
                *pyright.args,  # User-added arguments
                "-",  # Read input file paths from stdin
            ),
            input_digest=input_digest,
            description=f"Run Pyright on {pluralize(len(root_sources.snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
        **implicitly(),
    )

    # We must use relative paths, because we don't know the abspath of the sandbox the process
    # will run in, and `{chroot}` interpolation only works on argv, not on the contents of
    # __files.txt (see below). Pyright interprets relpaths as relative to its cwd, so we
    # prepend the appropriate prefix to each file path.
    input_path_prefix = os.path.relpath(".", process.working_directory)
    input_files = [os.path.join(input_path_prefix, file) for file in root_sources.snapshot.files]

    # We prefer to pass the list of input files via stdin, as large numbers of files can cause us
    # to exceed the max command line length.  See https://github.com/pantsbuild/pants/issues/22779.
    # However Pyright, weirdly, splits stdin on spaces as well as newlines. So we can't pass input
    # file paths via stdin if any of them contain spaces.
    file_with_spaces = next((file for file in root_sources.snapshot.files if " " in file), None)
    if file_with_spaces:
        # Fall back to passing paths as args and hope we don't exceed the max command line length.
        process = dataclasses.replace(process, argv=(*process.argv[0:-1], *input_files))
    else:
        # Write the input files out to a text file.
        file_list_path = "__files.txt"
        file_list_content = "\n".join(input_files).encode()
        file_list_digest = await create_digest(
            CreateDigest([FileContent(file_list_path, file_list_content)])
        )
        input_digest = await merge_digests(
            MergeDigests(
                [
                    process.input_digest,
                    file_list_digest,
                ]
            )
        )
        # Run the underlying process inside a shell script that cats the file list to stdin.
        shell_script = f"{cat_binary.path} {os.path.join(input_path_prefix, file_list_path)} | {shlex.join(process.argv)}"
        process = dataclasses.replace(
            process, argv=(sh_binary.path, "-c", shell_script), input_digest=input_digest
        )

    process = dataclasses.replace(process, cache_scope=check_subsystem.default_process_cache_scope)

    result = await execute_process(process, **implicitly())
    if result.exit_code == 249 and file_with_spaces:
        logger.error(
            f"Found input files with spaces in their names, including: {file_with_spaces}. "
            "Due to a bug in Pyright this means that the number of input files Pants can pass to "
            "Pyright is limited, and exceeding that limit causes it to crash with exit code 249. "
            "Please reach out to the Pants team if this happens: "
            "https://www.pantsbuild.org/community/getting-help."
        )
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

    coarsened_targets = await coarsened_targets_get(
        CoarsenedTargetsRequest(field_set.address for field_set in request.field_sets),
        **implicitly(),
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

    # Explicitly excluding `pyright` as a function argument to `pyright_determine_partitions` and `pyright_typecheck_partition`
    # as it throws "TypeError: unhashable type: 'Pyright'"
    partitions = await pyright_determine_partitions(request, **implicitly())
    partitioned_results = await concurrently(
        pyright_typecheck_partition(partition, **implicitly()) for partition in partitions
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
