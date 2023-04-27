# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap
from dataclasses import dataclass

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.util_rules import import_config
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.cgo_binaries import CGoBinaryPathRequest
from pants.backend.go.util_rules.import_config import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.link_defs import (
    ImplicitLinkerDependencies,
    ImplicitLinkerDependenciesHook,
)
from pants.backend.go.util_rules.sdk import GoSdkProcess, GoSdkToolIDRequest, GoSdkToolIDResult
from pants.core.util_rules.system_binaries import BashBinary, BinaryPath, BinaryPathTest
from pants.engine.fs import CreateDigest, Digest, Directory, FileContent
from pants.engine.internals.native_engine import AddPrefix, MergeDigests
from pants.engine.internals.selectors import MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionMembership
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class LinkGoBinaryRequest:
    """Link a Go binary from package archives and an import configuration."""

    input_digest: Digest
    archives: tuple[str, ...]
    build_opts: GoBuildOptions
    import_paths_to_pkg_a_files: FrozenDict[str, str]
    output_filename: str
    description: str


@dataclass(frozen=True)
class LinkedGoBinary:
    """A linked Go binary stored in a `Digest`."""

    digest: Digest


@dataclass(frozen=True)
class LinkerSetup:
    digest: Digest
    extld_wrapper_path: str


@rule
async def setup_go_linker(
    bash: BashBinary, golang_subsystem: GolangSubsystem.EnvironmentAware
) -> LinkerSetup:
    extld_binary = await Get(
        BinaryPath,
        CGoBinaryPathRequest(
            binary_name=golang_subsystem.external_linker_binary_name,
            binary_path_test=BinaryPathTest(["--version"]),
        ),
    )

    extld_wrapper_path = "__pants_extld_wrapper__"
    digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    path=extld_wrapper_path,
                    content=textwrap.dedent(
                        f"""\
                        #!{bash.path}
                        args=("${{@//__PANTS_SANDBOX_ROOT__/$__PANTS_SANDBOX_ROOT__}}")
                        exec {extld_binary.path} "${{args[@]}}"
                        """
                    ).encode(),
                    is_executable=True,
                ),
            ]
        ),
    )
    return LinkerSetup(digest, extld_wrapper_path)


@rule
async def link_go_binary(
    request: LinkGoBinaryRequest,
    linker_setup: LinkerSetup,
    union_membership: UnionMembership,
) -> LinkedGoBinary:
    implict_linker_deps_hooks = union_membership.get(ImplicitLinkerDependenciesHook)
    implicit_linker_deps = await MultiGet(
        Get(
            ImplicitLinkerDependencies,
            ImplicitLinkerDependenciesHook,
            hook(build_opts=request.build_opts),
        )
        for hook in implict_linker_deps_hooks
    )

    implicit_dep_digests = []
    import_paths_to_pkg_a_files = dict(request.import_paths_to_pkg_a_files)
    for implicit_linker_dep in implicit_linker_deps:
        for (
            dep_import_path,
            pkg_archive_path,
        ) in implicit_linker_dep.import_paths_to_pkg_a_files.items():
            if dep_import_path not in import_paths_to_pkg_a_files:
                import_paths_to_pkg_a_files[dep_import_path] = pkg_archive_path
                implicit_dep_digests.append(implicit_linker_dep.digest)

    link_tmp_dir = "link-tmp"
    link_tmp_dir_digest = await Get(Digest, CreateDigest([Directory(link_tmp_dir)]))

    link_tool_id, import_config = await MultiGet(
        Get(GoSdkToolIDResult, GoSdkToolIDRequest("link")),
        Get(
            ImportConfig,
            ImportConfigRequest(
                FrozenDict(import_paths_to_pkg_a_files), build_opts=request.build_opts
            ),
        ),
    )

    import_config_digest = await Get(Digest, AddPrefix(import_config.digest, link_tmp_dir))

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                request.input_digest,
                link_tmp_dir_digest,
                linker_setup.digest,
                import_config_digest,
                *implicit_dep_digests,
            ]
        ),
    )

    maybe_race_arg = ["-race"] if request.build_opts.with_race_detector else []
    maybe_msan_arg = ["-msan"] if request.build_opts.with_msan else []
    maybe_asan_arg = ["-asan"] if request.build_opts.with_asan else []

    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=(
                "tool",
                "link",
                # Put the linker's temporary directory into the input root.
                "-tmpdir",
                f"__PANTS_SANDBOX_ROOT__/{link_tmp_dir}",
                # Force `go tool link` to use a wrapper script as the "external linker" so that the script can
                # replace any instances of `__PANTS_SANDBOX_ROOT__` in the linker arguments. This also allows
                # Pants to know which external linker is in use and invalidate this `Process` as needed.
                "-extld",
                f"__PANTS_SANDBOX_ROOT__/{linker_setup.extld_wrapper_path}",
                *maybe_race_arg,
                *maybe_msan_arg,
                *maybe_asan_arg,
                "-importcfg",
                f"{link_tmp_dir}/{import_config.CONFIG_PATH}",
                "-o",
                request.output_filename,
                "-buildmode=exe",  # seen in `go build -x` output
                *request.build_opts.linker_flags,
                *request.archives,
            ),
            env={
                "__PANTS_GO_LINK_TOOL_ID": link_tool_id.tool_id,
            },
            description=f"Link Go binary: {request.output_filename}",
            output_files=(request.output_filename,),
            replace_sandbox_root_in_args=True,
        ),
    )

    return LinkedGoBinary(result.output_digest)


def rules():
    return (
        *collect_rules(),
        *import_config.rules(),
    )
