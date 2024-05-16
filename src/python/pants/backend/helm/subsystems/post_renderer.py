# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import pkgutil
import shlex
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent  # noqa: PNT20
from typing import Any, Iterable, Mapping

import yaml

from pants.backend.helm.utils.yaml import FrozenYamlIndex
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.core.util_rules.system_binaries import CatBinary
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.process import Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSetsPerTarget, FieldSetsPerTargetRequest, Targets
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list, pluralize, softwrap

logger = logging.getLogger(__name__)

_HELM_POSTRENDERER_SOURCE = "post_renderer_main.py"
_HELM_POSTRENDERER_PACKAGE = "pants.backend.helm.subsystems"


class HelmPostRendererSubsystem(PythonToolRequirementsBase):
    options_scope = "helm-post-renderer"
    help_short = "Used perform modifications to the final output produced by Helm charts when they've been fully rendered."

    default_requirements = [
        "yamlpath>=3.6.0,<4",
        "ruamel.yaml>=0.15.96,!=0.17.0,!=0.17.1,!=0.17.2,!=0.17.5,<=0.17.21",
    ]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<3.10"]

    default_lockfile_resource = (_HELM_POSTRENDERER_PACKAGE, "post_renderer.lock")


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
    extra_post_renderers: UnparsedAddressInputs | None = None

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

    def __init__(
        self,
        *,
        exe: str,
        digest: Digest,
        description_of_origin: str,
        env: Mapping[str, str] | None = None,
        immutable_input_digests: Mapping[str, Digest] | None = None,
        append_only_caches: Mapping[str, str] | None = None,
    ) -> None:
        object.__setattr__(self, "exe", exe)
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "description_of_origin", description_of_origin)
        object.__setattr__(self, "env", FrozenDict(env or {}))
        object.__setattr__(self, "append_only_caches", FrozenDict(append_only_caches or {}))
        object.__setattr__(
            self, "immutable_input_digests", FrozenDict(immutable_input_digests or {})
        )

    def level(self) -> LogLevel | None:
        return LogLevel.DEBUG

    def message(self) -> str | None:
        return f"runnable {self.exe} for {self.description_of_origin} is ready."

    def metadata(self) -> dict[str, Any] | None:
        return {
            "exe": self.exe,
            "env": self.env,
            "append_only_caches": self.append_only_caches,
            "description_of_origin": self.description_of_origin,
        }


async def _resolve_post_renderers(
    address_inputs: UnparsedAddressInputs,
) -> Iterable[RunRequest]:
    logger.debug(
        softwrap(
            f"""
            Resolving {pluralize(len(address_inputs.values), 'post-renderer')} from {address_inputs.description_of_origin}:

            {bullet_list(address_inputs.values, 5)}
            """
        )
    )

    targets = await Get(Targets, UnparsedAddressInputs, address_inputs)
    field_sets_per_target = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(RunFieldSet, targets)
    )
    return await MultiGet(
        Get(RunRequest, RunFieldSet, field_set) for field_set in field_sets_per_target.field_sets
    )


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
    post_renderer_input_file = os.path.join(".", "__helm_stdout.yaml")
    post_renderer_process = await Get(
        Process,
        VenvPexProcess(
            post_renderer_tool.pex,
            argv=[post_renderer_cfg_file, post_renderer_input_file],
            input_digest=post_renderer_cfg_digest,
            description="",
        ),
    )

    def shell_cmd(args: Iterable[str]) -> str:
        return " ".join([shlex.quote(arg) for arg in args])

    # Build a shell wrapper script which will be the actual entry-point sent to Helm as the post-renderer.
    # Extra post-renderers are plugged by piping the output of one into the next one in the order they
    # have been defined.
    extra_post_renderers = (
        await _resolve_post_renderers(request.extra_post_renderers)
        if request.extra_post_renderers
        else []
    )
    post_renderer_process_cli = " | ".join(
        [
            shell_cmd(post_renderer_process.argv),
            *[shell_cmd(post_renderer.args) for post_renderer in extra_post_renderers],
        ]
    )
    logger.debug(
        f'Using post-renderer pipeline "{post_renderer_process_cli}" in {request.description_of_origin}.'
    )

    postrenderer_wrapper_script = dedent(
        f"""\
        #!/bin/bash

        # Output stdin into a file in disk
        {cat_binary.path} <&0 > {post_renderer_input_file}

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

    # Combine all required settings for the internal and extra post-renderers
    launcher_digest = await Get(
        Digest,
        MergeDigests(
            [
                wrapper_digest,
                post_renderer_process.input_digest,
                *[post_renderer.digest for post_renderer in extra_post_renderers],
            ]
        ),
    )
    launcher_env = {
        **post_renderer_process.env,
        **{
            k: v
            for post_renderer in extra_post_renderers
            for k, v in post_renderer.extra_env.items()
        },
    }
    launcher_append_only_caches = {
        **post_renderer_process.append_only_caches,
        **{
            k: v
            for post_renderer in extra_post_renderers
            for k, v in (post_renderer.append_only_caches or {}).items()
        },
    }
    launcher_immutable_input_digests = {
        **post_renderer_process.immutable_input_digests,
        **{
            k: v
            for post_renderer in extra_post_renderers
            for k, v in (post_renderer.immutable_input_digests or {}).items()
        },
    }

    return HelmPostRenderer(
        exe=_HELM_POST_RENDERER_WRAPPER_SCRIPT,
        digest=launcher_digest,
        env=launcher_env,
        append_only_caches=launcher_append_only_caches,
        immutable_input_digests=launcher_immutable_input_digests,
        description_of_origin=request.description_of_origin,
    )


def rules():
    return [
        *collect_rules(),
        *pex.rules(),
    ]
