# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import hashlib
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.util_rules import import_config
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.cgo_binaries import CGoBinaryPathRequest, find_cgo_binary_path
from pants.backend.go.util_rules.goroot import GoRoot
from pants.backend.go.util_rules.import_config import ImportConfigRequest, generate_import_config
from pants.backend.go.util_rules.link_defs import (
    ImplicitLinkerDependenciesHook,
    get_implicit_linker_dependencies,
)
from pants.backend.go.util_rules.sdk import GoSdkProcess, GoSdkToolIDRequest, compute_go_tool_id
from pants.core.util_rules.system_binaries import BashBinary, BinaryPathTest
from pants.engine.fs import CreateDigest, Digest, Directory, FileContent
from pants.engine.internals.native_engine import AddPrefix, MergeDigests
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import add_prefix, create_digest, merge_digests
from pants.engine.process import fallible_to_exec_result_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
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
    extld_binary = await find_cgo_binary_path(
        CGoBinaryPathRequest(
            binary_name=golang_subsystem.external_linker_binary_name,
            binary_path_test=BinaryPathTest(["--version"]),
        ),
        **implicitly(),
    )

    extld_wrapper_path = "__pants_extld_wrapper__"
    digest = await create_digest(
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
        )
    )
    return LinkerSetup(digest, extld_wrapper_path)


def _compute_link_action_id(
    request: LinkGoBinaryRequest,
    goroot: GoRoot,
    link_tool_id: str,
    import_paths_to_pkg_a_files: Mapping[str, str],
) -> str:
    """Compute the Go toolchain build ID to record in the linked binary.

    This computation is intended to capture similar values to the action ID computed by the `go`
    tool for its own cache. For details, see `linkActionID` and `printLinkerConfig` in
    https://github.com/golang/go/blob/master/src/cmd/go/internal/work/exec.go
    """
    h = hashlib.sha256()

    # All Go action IDs have the full version (as returned by `runtime.Version()`) in the key.
    # See https://github.com/golang/go/blob/master/src/cmd/go/internal/cache/hash.go#L32-L46
    h.update(goroot.full_version.encode())

    h.update(b"link\n")
    h.update(f"goos {goroot.goos} goarch {goroot.goarch}\n".encode())
    h.update(f"link {link_tool_id}\n".encode())
    h.update(
        f"race {request.build_opts.with_race_detector} msan {request.build_opts.with_msan} "
        f"asan {request.build_opts.with_asan}\n".encode()
    )
    for flag in request.build_opts.linker_flags:
        h.update(f"linkflag {flag}\n".encode())
    h.update(f"out {request.output_filename}\n".encode())
    for import_path, pkg_a_file in sorted(import_paths_to_pkg_a_files.items()):
        h.update(f"packagefile {import_path}={pkg_a_file}\n".encode())
    for archive in request.archives:
        h.update(f"archive {archive}\n".encode())
    if "GOEXPERIMENT" in goroot._raw_metadata:
        h.update(f"GOEXPERIMENT={goroot._raw_metadata['GOEXPERIMENT']}\n".encode())

    # Inputs are included in this hash since it feeds the link buildid that is recorded in the
    # binary as its platform identity record. So it should distinguish different outputs.
    h.update(f"inputs {request.input_digest.fingerprint}\n".encode())

    return h.hexdigest()


@rule
async def link_go_binary(
    request: LinkGoBinaryRequest,
    linker_setup: LinkerSetup,
    union_membership: UnionMembership,
    goroot: GoRoot,
) -> LinkedGoBinary:
    implict_linker_deps_hooks = union_membership.get(ImplicitLinkerDependenciesHook)
    implicit_linker_deps = await concurrently(
        get_implicit_linker_dependencies(
            **implicitly({hook(build_opts=request.build_opts): ImplicitLinkerDependenciesHook})
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
    link_tmp_dir_digest = await create_digest(CreateDigest([Directory(link_tmp_dir)]))

    link_tool_id, import_config = await concurrently(
        compute_go_tool_id(GoSdkToolIDRequest("link")),
        generate_import_config(
            ImportConfigRequest(
                FrozenDict(import_paths_to_pkg_a_files), build_opts=request.build_opts
            )
        ),
    )

    import_config_digest = await add_prefix(AddPrefix(import_config.digest, link_tmp_dir))

    input_digest = await merge_digests(
        MergeDigests(
            [
                request.input_digest,
                link_tmp_dir_digest,
                linker_setup.digest,
                import_config_digest,
                *implicit_dep_digests,
            ]
        )
    )

    maybe_race_arg = ["-race"] if request.build_opts.with_race_detector else []
    maybe_msan_arg = ["-msan"] if request.build_opts.with_msan else []
    maybe_asan_arg = ["-asan"] if request.build_opts.with_asan else []

    build_id = _compute_link_action_id(
        request,
        goroot,
        link_tool_id.tool_id,
        import_paths_to_pkg_a_files,
    )

    result = await fallible_to_exec_result_or_raise(
        **implicitly(
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
                    "-buildid",
                    build_id,
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
    )

    return LinkedGoBinary(result.output_digest)


def rules():
    return (
        *collect_rules(),
        *import_config.rules(),
    )
