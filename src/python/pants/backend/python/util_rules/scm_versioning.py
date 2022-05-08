# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

import toml

from pants.backend.python.subsystems.setuptools_scm import SetuptoolsSCM
from pants.backend.python.target_types import (
    PythonSourceField,
    SetuptoolsSCMDummySourceField,
    SetuptoolsSCMTagRegexField,
    SetuptoolsSCMWriteToField,
    SetuptoolsSCMWriteToTemplateField,
)
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.vcs.git import GitWorktreeRequest, MaybeGitWorktree


class SCMVersioningError(Exception):
    pass


# Note that even though setuptools_scm is Python-centric, we could easily use it to generate
# version data for use in other languages!
class GeneratePythonFromSetuptoolsSCMRequest(GenerateSourcesRequest):
    input = SetuptoolsSCMDummySourceField
    output = PythonSourceField


@rule
async def generate_python_from_setuptools_scm(
    request: GeneratePythonFromSetuptoolsSCMRequest,
    setuptools_scm: SetuptoolsSCM,
) -> GeneratedSources:
    # A GitWorktreeRequest is uncacheable, so this enclosing rule will run every time its result
    # is needed, meaning it will always return a result based on the current underlying git state.
    maybe_git_worktree = await Get(MaybeGitWorktree, GitWorktreeRequest())
    if not maybe_git_worktree.git_worktree:
        raise SCMVersioningError("Not running in a git worktree")

    # Generate the setuptools_scm config. We don't use any existing pyproject.toml config,
    # because we don't want to let setuptools_scm itself write the output file. This is because
    # it would do so relative to the --root, meaning it will write outside the sandbox,
    # directly into the workspace, which is obviously not what we want.
    # It's unfortunate that setuptools_scm does not have separate config for "where is the .git
    # directory" and "where should I write output to".
    config: dict[str, dict[str, dict[str, str]]] = {}
    tool_config = config.setdefault("tool", {}).setdefault("setuptools_scm", {})
    tag_regex = request.protocol_target[SetuptoolsSCMTagRegexField].value
    if tag_regex:
        tool_config["tag_regex"] = tag_regex
    config_path = "pyproject.synthetic.toml"

    input_digest_get = Get(
        Digest,
        CreateDigest(
            [
                FileContent(config_path, toml.dumps(config).encode()),
            ]
        ),
    )

    setuptools_scm_pex_get = Get(VenvPex, PexRequest, setuptools_scm.to_pex_request())
    setuptools_scm_pex, input_digest = await MultiGet(setuptools_scm_pex_get, input_digest_get)

    argv = ["--root", str(maybe_git_worktree.git_worktree.worktree), "--config", config_path]

    result = await Get(
        ProcessResult,
        VenvPexProcess(
            setuptools_scm_pex,
            argv=argv,
            input_digest=input_digest,
            description=f"Run setuptools_scm for {request.protocol_target.address.spec}",
            level=LogLevel.INFO,
        ),
    )
    version = result.stdout.decode().strip()
    write_to = cast(str, request.protocol_target[SetuptoolsSCMWriteToField].value)
    write_to_template = cast(str, request.protocol_target[SetuptoolsSCMWriteToTemplateField].value)
    output_content = write_to_template.format(version=version)
    output_snapshot = await Get(
        Snapshot, CreateDigest([FileContent(write_to, output_content.encode())])
    )
    return GeneratedSources(output_snapshot)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GeneratePythonFromSetuptoolsSCMRequest),
    )
