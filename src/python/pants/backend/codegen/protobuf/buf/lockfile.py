# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate the `buf.lock` for a `buf.yaml` with BSR `deps:`.

The `buf.yaml` found via `[buf].config` or discovery is one resolve, named after its
directory (`buf` at the repository root). `pants generate-lockfiles` runs
`buf dep update` for it, writing `buf.lock` next to `buf.yaml`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from pants.backend.codegen.protobuf.buf.config import find_buf_config_files
from pants.backend.codegen.protobuf.buf.subsystem import BufSubsystem
from pants.core.goals.generate_lockfiles import (
    GenerateLockfile,
    GenerateLockfileResult,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    RequestedUserResolveNames,
    UserGenerateLockfiles,
)
from pants.core.util_rules import config_files
from pants.core.util_rules.external_tool import download_external_tool
from pants.engine.fs import MergeDigests, PathGlobs
from pants.engine.intrinsics import merge_digests, path_globs_to_digest
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope, execute_process_or_raise
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


class KnownBufResolveNamesRequest(KnownUserResolveNamesRequest):
    pass


class RequestedBufResolveNames(RequestedUserResolveNames):
    pass


@dataclass(frozen=True)
class GenerateBufLockfile(GenerateLockfile):
    """A request to (re)generate `buf.lock` for a single buf module."""

    buf_yaml_path: str


def _resolve_name(buf_yaml_path: str) -> str:
    parent = os.path.dirname(buf_yaml_path)
    return parent if parent else "buf"


@rule
async def known_buf_user_resolve_names(
    _: KnownBufResolveNamesRequest, buf: BufSubsystem
) -> KnownUserResolveNames:
    files = await find_buf_config_files(buf)
    yaml_paths = sorted(p for p in files.snapshot.files if os.path.basename(p) == "buf.yaml")
    return KnownUserResolveNames(
        names=tuple(_resolve_name(p) for p in yaml_paths),
        option_name="`buf.yaml` discovery",
        requested_resolve_names_cls=RequestedBufResolveNames,
    )


@rule
async def setup_user_buf_lockfile_requests(
    requested: RequestedBufResolveNames, buf: BufSubsystem
) -> UserGenerateLockfiles:
    files = await find_buf_config_files(buf)
    name_to_yaml = {
        _resolve_name(p): p for p in files.snapshot.files if os.path.basename(p) == "buf.yaml"
    }
    requests = []
    for name in requested:
        path = name_to_yaml.get(name)
        if path is None:
            continue
        requests.append(
            GenerateBufLockfile(
                resolve_name=name,
                lockfile_dest=os.path.join(os.path.dirname(path), "buf.lock"),
                diff=False,
                buf_yaml_path=path,
            )
        )
    return UserGenerateLockfiles(requests)


@rule(desc="Resolve buf.yaml deps via `buf dep update`", level=LogLevel.DEBUG)
async def generate_buf_lockfile(
    req: GenerateBufLockfile, buf: BufSubsystem, platform: Platform
) -> GenerateLockfileResult:
    buf_yaml_dir = os.path.dirname(req.buf_yaml_path) or "."

    # `buf dep update` does a partial build, so it needs at least one `.proto`
    # file in the module to operate. Glob them in alongside the buf.yaml/buf.lock.
    proto_glob = f"{buf_yaml_dir}/**/*.proto" if buf_yaml_dir != "." else "**/*.proto"
    downloaded_buf, files, protos_digest = await concurrently(
        download_external_tool(buf.get_request(platform)),
        find_buf_config_files(buf),
        path_globs_to_digest(PathGlobs([proto_glob])),
    )

    input_digest = await merge_digests(
        MergeDigests((files.snapshot.digest, protos_digest, downloaded_buf.digest))
    )

    process_result = await execute_process_or_raise(
        **implicitly(
            Process(
                argv=[downloaded_buf.exe, "dep", "update", buf_yaml_dir],
                input_digest=input_digest,
                description=f"Resolving buf.lock for `{req.resolve_name}`",
                level=LogLevel.DEBUG,
                output_files=(req.lockfile_dest,),
                # Resolves `deps:` against the BSR's current state, which the cache key can't see.
                cache_scope=ProcessCacheScope.PER_SESSION,
            )
        )
    )

    return GenerateLockfileResult(
        digest=process_result.output_digest,
        resolve_name=req.resolve_name,
        path=req.lockfile_dest,
    )


def rules():
    return [
        *collect_rules(),
        *config_files.rules(),
        UnionRule(GenerateLockfile, GenerateBufLockfile),
        UnionRule(KnownUserResolveNamesRequest, KnownBufResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedBufResolveNames),
    ]
