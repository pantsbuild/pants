# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import pkgutil
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent
from typing import Any

import yaml

from pants.backend.helm.utils.yaml import FrozenYamlIndex
from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_requirements import GeneratePythonToolLockfileSentinel
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.system_binaries import CatBinary
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.process import Process
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.docutil import git_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)

_HELM_POSTRENDERER_SOURCE = "post_renderer_main.py"
_HELM_POSTRENDERER_PACKAGE = "pants.backend.helm.subsystems"


class HelmPostRendererSubsystem(PythonToolRequirementsBase):
    options_scope = "helm-post-renderer"
    help = "Used perform modifications to the final output produced by Helm charts when they've been fully rendered."

    default_version = "yamlpath>=3.6,<3.7"
    default_extra_requirements = [
        "ruamel.yaml>=0.15.96,!=0.17.0,!=0.17.1,!=0.17.2,!=0.17.5,<=0.17.21"
    ]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<3.10"]

    register_lockfile = True
    default_lockfile_resource = (_HELM_POSTRENDERER_PACKAGE, "post_renderer.lock")
    default_lockfile_path = (
        f"src/python/{_HELM_POSTRENDERER_PACKAGE.replace('.', '/')}/post_renderer.lock"
    )
    default_lockfile_url = git_url(default_lockfile_path)


class HelmPostRendererLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = HelmPostRendererSubsystem.options_scope


@rule
def setup_postrenderer_lockfile_request(
    _: HelmPostRendererLockfileSentinel,
    post_renderer: HelmPostRendererSubsystem,
    python_setup: PythonSetup,
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(
        post_renderer, use_pex=python_setup.generate_lockfiles_with_pex
    )


_HELM_POST_RENDERER_TOOL = "__pants_helm_post_renderer.py"


@dataclass(frozen=True)
class _HelmPostRendererTool:
    pex: VenvPex


@rule(desc="Setup Helm post renderer binaries", level=LogLevel.DEBUG)
async def setup_post_renderer_tool(
    post_renderer: HelmPostRendererSubsystem,
) -> _HelmPostRendererTool:
    post_renderer_sources = pkgutil.get_data(_HELM_POSTRENDERER_PACKAGE, _HELM_POSTRENDERER_SOURCE)
    if not post_renderer_sources:
        raise ValueError(
            f"Unable to find source to {_HELM_POSTRENDERER_SOURCE!r} in {_HELM_POSTRENDERER_PACKAGE}"
        )

    post_renderer_content = FileContent(
        path=_HELM_POST_RENDERER_TOOL, content=post_renderer_sources, is_executable=True
    )
    post_renderer_digest = await Get(Digest, CreateDigest([post_renderer_content]))

    post_renderer_pex = await Get(
        VenvPex,
        PexRequest,
        post_renderer.to_pex_request(
            main=EntryPoint(PurePath(post_renderer_content.path).stem), sources=post_renderer_digest
        ),
    )
    return _HelmPostRendererTool(post_renderer_pex)


HELM_POST_RENDERER_CFG_FILENAME = "post_renderer.cfg.yaml"
_HELM_POST_RENDERER_WRAPPER_SCRIPT = "post_renderer_wrapper.sh"


@dataclass(frozen=True)
class SetupHelmPostRenderer(EngineAwareParameter):
    """Request for a post-renderer process that will perform a series of replacements in the
    generated files."""

    replacements: FrozenYamlIndex[str]
    description_of_origin: str

    def debug_hint(self) -> str | None:
        return self.description_of_origin


@dataclass(frozen=True)
class HelmPostRenderer(EngineAwareReturnType):
    exe: str
    digest: Digest
    immutable_input_digests: FrozenDict[str, Digest]
    env: FrozenDict[str, str]
    append_only_caches: FrozenDict[str, str]
    description_of_origin: str

    def level(self) -> LogLevel | None:
        return LogLevel.DEBUG

    def message(self) -> str | None:
        return f"runnable {self.exe} for {self.description_of_origin} is ready."

    def metadata(self) -> dict[str, Any] | None:
        return {"exe": self.exe, "env": self.env, "append_only_caches": self.append_only_caches}


@rule(desc="Configure Helm post-renderer", level=LogLevel.DEBUG)
async def setup_post_renderer_launcher(
    request: SetupHelmPostRenderer,
    post_renderer_tool: _HelmPostRendererTool,
    cat_binary: CatBinary,
) -> HelmPostRenderer:
    # Build post-renderer configuration file and create a digest containing it.
    post_renderer_config = yaml.safe_dump(
        request.replacements.to_json_dict(), explicit_start=True, sort_keys=True
    )
    post_renderer_cfg_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(HELM_POST_RENDERER_CFG_FILENAME, post_renderer_config.encode("utf-8")),
            ]
        ),
    )

    # Generate a temporary PEX process that uses the previously created configuration file.
    post_renderer_cfg_file = os.path.join(".", HELM_POST_RENDERER_CFG_FILENAME)
    post_renderer_stdin_file = os.path.join(".", "__stdin.yaml")
    post_renderer_process = await Get(
        Process,
        VenvPexProcess(
            post_renderer_tool.pex,
            argv=[post_renderer_cfg_file, post_renderer_stdin_file],
            input_digest=post_renderer_cfg_digest,
            description="",
        ),
    )

    # Build a shell wrapper script which will be the actual entry-point sent to Helm as the post-renderer.
    post_renderer_process_cli = " ".join(post_renderer_process.argv)
    logger.debug(f"Built post-renderer process CLI: {post_renderer_process_cli}")

    postrenderer_wrapper_script = dedent(
        f"""\
        #!/bin/bash

        # Output stdin into a file in disk
        {cat_binary.path} <&0 > {post_renderer_stdin_file}

        {post_renderer_process_cli}
        """
    )
    wrapper_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    _HELM_POST_RENDERER_WRAPPER_SCRIPT,
                    postrenderer_wrapper_script.encode("utf-8"),
                    is_executable=True,
                ),
            ]
        ),
    )

    # Extract all info needed to invoke the post-renderer from the PEX process
    launcher_digest = await Get(
        Digest, MergeDigests([wrapper_digest, post_renderer_process.input_digest])
    )
    return HelmPostRenderer(
        exe=_HELM_POST_RENDERER_WRAPPER_SCRIPT,
        digest=launcher_digest,
        env=post_renderer_process.env,
        append_only_caches=post_renderer_process.append_only_caches,
        immutable_input_digests=post_renderer_process.immutable_input_digests,
        description_of_origin=request.description_of_origin,
    )


def rules():
    return [
        *collect_rules(),
        *pex.rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, HelmPostRendererLockfileSentinel),
    ]
