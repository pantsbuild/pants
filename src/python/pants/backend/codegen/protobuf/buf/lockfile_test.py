# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

import pytest

from pants.backend.codegen.protobuf.buf.config import buf_resolve_name, find_buf_config_files
from pants.backend.codegen.protobuf.buf.lockfile import (
    GenerateBufLockfile,
    KnownBufResolveNamesRequest,
    RequestedBufResolveNames,
)
from pants.backend.codegen.protobuf.buf.lockfile import (
    rules as lockfile_rules,
)
from pants.backend.codegen.protobuf.buf.subsystem import BufSubsystem
from pants.core.goals.generate_lockfiles import KnownUserResolveNames, UserGenerateLockfiles
from pants.engine.rules import rule
from pants.testutil.rule_runner import QueryRule, RuleRunner


@dataclass(frozen=True)
class BufConfigFilePaths:
    paths: tuple[str, ...]


@rule
async def buf_config_file_paths_for_test(buf: BufSubsystem) -> BufConfigFilePaths:
    return BufConfigFilePaths((await find_buf_config_files(buf)).snapshot.files)


BUF_YAML_WITH_DEPS = (
    "version: v2\nmodules:\n  - path: .\ndeps:\n  - buf.build/bufbuild/protovalidate\n"
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *lockfile_rules(),
            buf_config_file_paths_for_test,
            QueryRule(BufConfigFilePaths, []),
            QueryRule(KnownUserResolveNames, [KnownBufResolveNamesRequest]),
            QueryRule(UserGenerateLockfiles, [RequestedBufResolveNames]),
        ],
    )


@pytest.mark.parametrize("with_lock", [True, False])
def test_config_option_keeps_sibling_lock(rule_runner: RuleRunner, with_lock: bool) -> None:
    rule_runner.write_files(
        {
            "proto/buf.yaml": "version: v2\n",
            **({"proto/buf.lock": "version: v2\n"} if with_lock else {}),
            # Not beside the configured `buf.yaml`, so not picked up.
            "buf.lock": "version: v2\n",
        }
    )
    rule_runner.set_options(["--buf-config=proto/buf.yaml"])
    result = rule_runner.request(BufConfigFilePaths, [])
    assert result.paths == (
        ("proto/buf.lock", "proto/buf.yaml") if with_lock else ("proto/buf.yaml",)
    )


def test_resolve_name_uses_parent_directory_or_buf_for_root() -> None:
    assert buf_resolve_name("buf.yaml") == "buf"
    assert buf_resolve_name("idl/buf.yaml") == "idl"
    assert buf_resolve_name("a/b/c/buf.yaml") == "a/b/c"


def test_known_resolve_names_finds_repo_root_buf_yaml(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"buf.yaml": BUF_YAML_WITH_DEPS})
    result = rule_runner.request(KnownUserResolveNames, [KnownBufResolveNamesRequest()])
    assert result.names == ("buf",)
    assert result.requested_resolve_names_cls is RequestedBufResolveNames


def test_known_resolve_names_skips_buf_yaml_without_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"buf.yaml": "version: v2\nmodules:\n  - path: .\n"})
    result = rule_runner.request(KnownUserResolveNames, [KnownBufResolveNamesRequest()])
    assert result.names == ()


def test_known_resolve_names_returns_empty_when_no_buf_yaml(rule_runner: RuleRunner) -> None:
    result = rule_runner.request(KnownUserResolveNames, [KnownBufResolveNamesRequest()])
    assert result.names == ()


def test_setup_lockfile_requests_maps_resolve_name_to_buf_yaml(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"buf.yaml": BUF_YAML_WITH_DEPS})
    result = rule_runner.request(UserGenerateLockfiles, [RequestedBufResolveNames(["buf"])])
    [req] = result
    assert isinstance(req, GenerateBufLockfile)
    assert req.resolve_name == "buf"
    assert req.buf_yaml_path == "buf.yaml"
    assert req.lockfile_dest == "buf.lock"


def test_setup_lockfile_requests_skips_unknown_resolve_names(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"buf.yaml": BUF_YAML_WITH_DEPS})
    result = rule_runner.request(UserGenerateLockfiles, [RequestedBufResolveNames(["nonexistent"])])
    assert list(result) == []
