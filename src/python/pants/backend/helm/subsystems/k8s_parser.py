# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import pkgutil
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules.pex import PexRequest, VenvPex
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.rules import Get, collect_rules, rule
from pants.util.docutil import git_url

logger = logging.getLogger(__name__)

_HELM_K8S_PARSER_SOURCE = "k8s_parser_main.py"
_HELM_K8S_PARSER_PACKAGE = "pants.backend.helm.subsystems"


class HelmKubeParserSubsystem(PythonToolRequirementsBase):
    options_scope = "helm-k8s-parser"
    help = "Used perform modifications to the final output produced by Helm charts when they've been fully rendered."

    default_version = "kubernetes>=24.2.0,<25.0"
    default_extra_requirements = ["types-kubernetes>=18.20.0,<19.0"]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<3.10"]

    register_lockfile = True
    default_lockfile_resource = (_HELM_K8S_PARSER_PACKAGE, "k8s_parser.lock")
    default_lockfile_path = (
        f"src/python/{_HELM_K8S_PARSER_PACKAGE.replace('.', '/')}/k8s_parser.lock"
    )
    default_lockfile_url = git_url(default_lockfile_path)


class HelmKubeParserLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = HelmKubeParserSubsystem.options_scope


@rule
def setup_k8s_parser_lockfile_request(
    _: HelmKubeParserLockfileSentinel,
    post_renderer: HelmKubeParserSubsystem,
    python_setup: PythonSetup,
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(
        post_renderer, use_pex=python_setup.generate_lockfiles_with_pex
    )


@dataclass(frozen=True)
class _HelmKubeParserTool:
    pex: VenvPex


@rule
async def build_k8s_parser_tool(k8s_parser: HelmKubeParserSubsystem) -> _HelmKubeParserTool:
    parser_sources = pkgutil.get_data(_HELM_K8S_PARSER_PACKAGE, _HELM_K8S_PARSER_SOURCE)
    if not parser_sources:
        raise ValueError(
            f"Unable to find source to {_HELM_K8S_PARSER_SOURCE!r} in {_HELM_K8S_PARSER_PACKAGE}"
        )

    parser_file_content = FileContent(
        path="__k8s_parser.py", content=parser_sources, is_executable=True
    )
    parser_digest = await Get(Digest, CreateDigest([parser_file_content]))

    parser_pex = await Get(
        VenvPex,
        PexRequest,
        k8s_parser.to_pex_request(
            main=EntryPoint(PurePath(parser_file_content.path).stem), sources=parser_digest
        ),
    )
    return _HelmKubeParserTool(parser_pex)


def rules():
    return collect_rules()
