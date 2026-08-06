# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.codegen.protobuf.buf.lockfile import (
    GenerateBufLockfile,
    KnownBufResolveNamesRequest,
    RequestedBufResolveNames,
    _resolve_name,
)
from pants.backend.codegen.protobuf.buf.lockfile import (
    rules as lockfile_rules,
)
from pants.core.goals.generate_lockfiles import KnownUserResolveNames, UserGenerateLockfiles
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *lockfile_rules(),
            QueryRule(KnownUserResolveNames, [KnownBufResolveNamesRequest]),
            QueryRule(UserGenerateLockfiles, [RequestedBufResolveNames]),
        ],
    )


def test_resolve_name_uses_parent_directory_or_buf_for_root() -> None:
    assert _resolve_name("buf.yaml") == "buf"
    assert _resolve_name("idl/buf.yaml") == "idl"
    assert _resolve_name("a/b/c/buf.yaml") == "a/b/c"


def test_known_resolve_names_finds_repo_root_buf_yaml(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"buf.yaml": "version: v2\nmodules:\n  - path: .\n"})
    result = rule_runner.request(KnownUserResolveNames, [KnownBufResolveNamesRequest()])
    assert result.names == ("buf",)
    assert result.requested_resolve_names_cls is RequestedBufResolveNames


def test_known_resolve_names_returns_empty_when_no_buf_yaml(rule_runner: RuleRunner) -> None:
    result = rule_runner.request(KnownUserResolveNames, [KnownBufResolveNamesRequest()])
    assert result.names == ()


def test_setup_lockfile_requests_maps_resolve_name_to_buf_yaml(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"buf.yaml": "version: v2\nmodules:\n  - path: .\n"})
    result = rule_runner.request(UserGenerateLockfiles, [RequestedBufResolveNames(["buf"])])
    [req] = result
    assert isinstance(req, GenerateBufLockfile)
    assert req.resolve_name == "buf"
    assert req.buf_yaml_path == "buf.yaml"
    assert req.lockfile_dest == "buf.lock"


def test_setup_lockfile_requests_skips_unknown_resolve_names(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"buf.yaml": "version: v2\nmodules:\n  - path: .\n"})
    result = rule_runner.request(UserGenerateLockfiles, [RequestedBufResolveNames(["nonexistent"])])
    assert list(result) == []
