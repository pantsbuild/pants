# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict, cast

import toml

from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonMappingImpl,
    FirstPartyPythonMappingImplMarker,
    ModuleProvider,
    ModuleProviderType,
    ResolveName,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.subsystems.setuptools_scm import SetuptoolsSCM
from pants.backend.python.target_types import (
    PythonResolveField,
    PythonSourceField,
    VCSVersion,
    VCSVersionDummySourceField,
    VersionGenerateToField,
    VersionLocalSchemeField,
    VersionTagRegexField,
    VersionTemplateField,
    VersionVersionSchemeField,
)
from pants.backend.python.util_rules.pex import PexRequest, VenvPexProcess, create_venv_pex
from pants.core.util_rules.stripped_source_files import StrippedFileNameRequest, strip_file_name
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest, digest_to_snapshot, execute_process
from pants.engine.process import ProcessCacheScope
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import AllTargets, GeneratedSources, GenerateSourcesRequest, Targets
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap
from pants.vcs.git import GitWorktreeRequest, get_git_worktree


class VCSVersioningError(Exception):
    pass


# Note that even though setuptools_scm is Python-centric, we could easily use it to generate
# version data for use in other languages!
class GeneratePythonFromSetuptoolsSCMRequest(GenerateSourcesRequest):
    input = VCSVersionDummySourceField
    output = PythonSourceField


@rule
async def generate_python_from_setuptools_scm(
    request: GeneratePythonFromSetuptoolsSCMRequest,
    setuptools_scm: SetuptoolsSCM,
    local_environment_name: ChosenLocalEnvironmentName,
) -> GeneratedSources:
    # A MaybeGitWorktree is uncacheable, so this enclosing rule will run every time its result
    # is needed, and the process invocation below caches at session scope, meaning this rule
    # will always return a result based on the current underlying git state.
    maybe_git_worktree = await get_git_worktree(
        **implicitly(
            {GitWorktreeRequest(): GitWorktreeRequest, local_environment_name.val: EnvironmentName}
        )
    )
    if not maybe_git_worktree.git_worktree:
        raise VCSVersioningError(
            softwrap(
                f"""
                Trying to determine the version for the {request.protocol_target.address} target at
                {request.protocol_target.address}, but {maybe_git_worktree.failure_reason}.
                """
            )
        )

    # Generate the setuptools_scm config. We don't use any existing pyproject.toml config,
    # because we don't want to let setuptools_scm itself write the output file. This is because
    # it would do so relative to the --root, meaning it will write outside the sandbox,
    # directly into the workspace, which is obviously not what we want.
    # It's unfortunate that setuptools_scm does not have separate config for "where is the .git
    # directory" and "where should I write output to".
    config: dict[str, dict[str, dict[str, str]]] = {}
    tool_config = config.setdefault("tool", {}).setdefault("setuptools_scm", {})
    if tag_regex := request.protocol_target[VersionTagRegexField].value:
        tool_config["tag_regex"] = tag_regex
    if version_scheme := request.protocol_target[VersionVersionSchemeField].value:
        tool_config["version_scheme"] = version_scheme
    if local_scheme := request.protocol_target[VersionLocalSchemeField].value:
        tool_config["local_scheme"] = local_scheme
    config_path = "pyproject.synthetic.toml"

    input_digest_get = create_digest(
        CreateDigest(
            [
                FileContent(config_path, toml.dumps(config).encode()),
            ]
        )
    )

    setuptools_scm_pex_get = create_venv_pex(
        **implicitly(
            {
                setuptools_scm.to_pex_request(): PexRequest,
                local_environment_name.val: EnvironmentName,
            }
        )
    )
    setuptools_scm_pex, input_digest = await concurrently(setuptools_scm_pex_get, input_digest_get)

    argv = ["--root", str(maybe_git_worktree.git_worktree.worktree), "--config", config_path]

    result = await execute_process(
        **implicitly(
            {
                VenvPexProcess(
                    setuptools_scm_pex,
                    argv=argv,
                    input_digest=input_digest,
                    description=f"Run setuptools_scm for {request.protocol_target.address.spec}",
                    level=LogLevel.INFO,
                    cache_scope=ProcessCacheScope.PER_SESSION,
                ): VenvPexProcess,
                local_environment_name.val: EnvironmentName,
            }
        ),
    )
    version = result.stdout.decode().strip()
    write_to = cast(str, request.protocol_target[VersionGenerateToField].value)
    write_to_template = cast(str, request.protocol_target[VersionTemplateField].value)
    output_content = write_to_template.format(version=version)
    output_snapshot = await digest_to_snapshot(
        **implicitly(CreateDigest([FileContent(write_to, output_content.encode())]))
    )
    return GeneratedSources(output_snapshot)


# This is only used to register our implementation with the plugin hook via unions.
class PythonVCSVersionMappingMarker(FirstPartyPythonMappingImplMarker):
    pass


class VCSVersionPythonResolveField(PythonResolveField):
    alias = "python_resolve"


class AllVCSVersionTargets(Targets):
    # This class exists so map_to_python_modules isn't invalidated on any change to any target.
    pass


@rule(desc="Find all vcs_version targets in project", level=LogLevel.DEBUG)
async def find_all_vcs_version_targets(targets: AllTargets) -> AllVCSVersionTargets:
    return AllVCSVersionTargets(tgt for tgt in targets if tgt.has_field(VersionGenerateToField))


@rule
async def map_to_python_modules(
    vcs_version_targets: AllVCSVersionTargets,
    python_setup: PythonSetup,
    _: PythonVCSVersionMappingMarker,
) -> FirstPartyPythonMappingImpl:
    suffix = ".py"

    targets = [
        tgt
        for tgt in vcs_version_targets
        if cast(str, tgt[VersionGenerateToField].value).endswith(suffix)
    ]
    stripped_files = await concurrently(
        strip_file_name(StrippedFileNameRequest(cast(str, tgt[VersionGenerateToField].value)))
        for tgt in targets
    )
    resolves_to_modules_to_providers: DefaultDict[
        ResolveName, DefaultDict[str, list[ModuleProvider]]
    ] = defaultdict(lambda: defaultdict(list))
    for tgt, stripped_file in zip(targets, stripped_files):
        resolve = tgt[PythonResolveField].normalized_value(python_setup)
        module = stripped_file.value[: -len(suffix)].replace("/", ".")
        resolves_to_modules_to_providers[resolve][module].append(
            ModuleProvider(tgt.address, ModuleProviderType.IMPL)
        )
    return FirstPartyPythonMappingImpl.create(resolves_to_modules_to_providers)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GeneratePythonFromSetuptoolsSCMRequest),
        UnionRule(FirstPartyPythonMappingImplMarker, PythonVCSVersionMappingMarker),
        VCSVersion.register_plugin_field(VCSVersionPythonResolveField),
    )
