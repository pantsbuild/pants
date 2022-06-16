# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import pkgutil
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent

from pants.backend.helm.util_rules.yaml_utils import HelmManifestItems
from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.system_binaries import CatBinary
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.process import Process
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.docutil import git_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

_HELM_POSTRENDERER_SOURCE = "post_renderer_launcher.py"
_HELM_POSTRENDERER_PACKAGE = "pants.backend.helm.subsystems"


class HelmPostRenderer(PythonToolRequirementsBase):
    options_scope = "helm-post-renderer"
    help = "Used perform modifications to the final output produced by Helm charts when they've been fully rendered."

    default_version = "yamlpath>=3.6,<3.7"
    default_extra_requirements = [
        "ruamel.yaml>=0.15.96,!=0.17.0,!=0.17.1,!=0.17.2,!=0.17.5,<=0.17.17"
    ]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<3.10"]

    register_lockfile = True
    default_lockfile_resource = (_HELM_POSTRENDERER_PACKAGE, "post_renderer.lock")
    default_lockfile_path = (
        f"src/python/{_HELM_POSTRENDERER_PACKAGE.replace('.', '/')}/post_renderer.lock"
    )
    default_lockfile_url = git_url(default_lockfile_path)


class HelmPostRendererLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = HelmPostRenderer.options_scope


@rule
def setup_postrenderer_lockfile_request(
    _: HelmPostRendererLockfileSentinel, post_renderer: HelmPostRenderer, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(
        post_renderer, use_pex=python_setup.generate_lockfiles_with_pex
    )


_HELM_POST_RENDERER_TOOL = "__pants_helm_post_renderer.py"


@dataclass(frozen=True)
class InternalHelmPostRendererSetup:
    pex: VenvPex


@rule(desc="Prepare Helm post renderer", level=LogLevel.DEBUG)
async def setup_internal_post_renderer(
    post_renderer: HelmPostRenderer,
) -> InternalHelmPostRendererSetup:
    post_renderer_sources = pkgutil.get_data(_HELM_POSTRENDERER_PACKAGE, _HELM_POSTRENDERER_SOURCE)
    if not post_renderer_sources:
        raise ValueError(
            f"Unable to file sounce to {_HELM_POSTRENDERER_SOURCE!r} in {_HELM_POSTRENDERER_PACKAGE}"
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
    return InternalHelmPostRendererSetup(post_renderer_pex)


HELM_POST_RENDERER_CFG_FILENAME = "post_renderer.cfg.yaml"
_HELM_POST_RENDERER_WRAPPER_SCRIPT = "post_renderer_wrapper.sh"


@dataclass(frozen=True)
class SetupPostRendererLauncher:
    replacements: HelmManifestItems[str]


@dataclass(frozen=True)
class PostRendererLauncherSetup:
    exe: str
    digest: Digest
    immutable_input_digests: FrozenDict[str, Digest]
    env: FrozenDict[str, str]
    append_only_caches: FrozenDict[str, str]


@rule(desc="Configure Helm Post Renderer", level=LogLevel.DEBUG)
async def setup_post_renderer_launcher(
    request: SetupPostRendererLauncher,
    post_renderer: InternalHelmPostRendererSetup,
    cat_binary: CatBinary,
) -> PostRendererLauncherSetup:
    post_renderer_config = "---\n"
    for manifest in request.replacements.manifests():
        post_renderer_config += f'"{manifest}":\n'
        for path, replacement in request.replacements.manifest_items(manifest):
            post_renderer_config += f'  "{path}": "{replacement}"\n'

    post_renderer_cfg_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(HELM_POST_RENDERER_CFG_FILENAME, post_renderer_config.encode("utf-8")),
            ]
        ),
    )

    post_renderer_stdin_file = os.path.join(".", "__stdin.yaml")
    post_renderer_process = await Get(
        Process,
        VenvPexProcess(
            post_renderer.pex,
            argv=[os.path.join(".", HELM_POST_RENDERER_CFG_FILENAME), post_renderer_stdin_file],
            input_digest=post_renderer_cfg_digest,
            description="",
        ),
    )

    postrenderer_wrapper_script = dedent(
        f"""\
        #!/bin/bash

        # Output stdin into a file in disk
        {cat_binary.path} <&0 > {post_renderer_stdin_file}

        {' '.join(post_renderer_process.argv)}
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

    launcher_digest = await Get(
        Digest, MergeDigests([wrapper_digest, post_renderer_process.input_digest])
    )
    return PostRendererLauncherSetup(
        exe=_HELM_POST_RENDERER_WRAPPER_SCRIPT,
        digest=launcher_digest,
        env=post_renderer_process.env,
        append_only_caches=post_renderer_process.append_only_caches,
        immutable_input_digests=post_renderer_process.immutable_input_digests,
    )


def rules():
    return [
        *collect_rules(),
        *pex.rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, HelmPostRendererLockfileSentinel),
    ]
