# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import pkgutil
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from pants.backend.helm.utils.yaml import YamlPath
from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_requirements import GeneratePythonToolLockfileSentinel
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import CreateDigest, Digest, FileContent, FileEntry
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.docutil import git_url
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize, softwrap

logger = logging.getLogger(__name__)

_HELM_K8S_PARSER_SOURCE = "k8s_parser_main.py"
_HELM_K8S_PARSER_PACKAGE = "pants.backend.helm.subsystems"


class HelmKubeParserSubsystem(PythonToolRequirementsBase):
    options_scope = "helm-k8s-parser"
    help = "Analyses K8S manifests rendered by Helm."

    default_version = "hikaru==0.11.0b"

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<3.10"]

    register_lockfile = True
    default_lockfile_resource = (_HELM_K8S_PARSER_PACKAGE, "k8s_parser.lock")
    default_lockfile_path = (
        f"src/python/{_HELM_K8S_PARSER_PACKAGE.replace('.', '/')}/k8s_parser.lock"
    )
    default_lockfile_url = git_url(default_lockfile_path)


class HelmKubeParserLockfileSentinel(GeneratePythonToolLockfileSentinel):
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


@dataclass(frozen=True)
class ParseKubeManifestRequest(EngineAwareParameter):
    file: FileEntry

    def debug_hint(self) -> str | None:
        return self.file.path

    def metadata(self) -> dict[str, Any] | None:
        return {"file": self.file}


@dataclass(frozen=True)
class ParsedKubeManifest(EngineAwareReturnType):
    filename: str
    found_image_refs: tuple[tuple[int, YamlPath, str], ...]

    def level(self) -> LogLevel | None:
        return LogLevel.DEBUG

    def message(self) -> str | None:
        return f"Found {pluralize(len(self.found_image_refs), 'image reference')} in file {self.filename}"

    def metadata(self) -> dict[str, Any] | None:
        return {
            "filename": self.filename,
            "found_image_refs": self.found_image_refs,
        }


@rule(desc="Parse Kubernetes resource manifest")
async def parse_kube_manifest(
    request: ParseKubeManifestRequest, tool: _HelmKubeParserTool
) -> ParsedKubeManifest:
    file_digest = await Get(Digest, CreateDigest([request.file]))

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            tool.pex,
            argv=[request.file.path],
            input_digest=file_digest,
            description=f"Analyzing Kubernetes manifest {request.file.path}",
            level=LogLevel.DEBUG,
        ),
    )

    if result.exit_code == 0:
        output = result.stdout.decode("utf-8").splitlines()
        image_refs: list[tuple[int, YamlPath, str]] = []
        for line in output:
            parts = line.split(",")
            if len(parts) != 3:
                raise Exception(
                    softwrap(
                        f"""Unexpected output from k8s parser when parsing file {request.file.path}:

                        {line}
                        """
                    )
                )

            image_refs.append((int(parts[0]), YamlPath.parse(parts[1]), parts[2]))

        return ParsedKubeManifest(filename=request.file.path, found_image_refs=tuple(image_refs))
    else:
        parser_error = result.stderr.decode("utf-8")
        raise Exception(
            softwrap(
                f"""
                Could not parse Kubernetes manifests in file: {request.file.path}.
                {parser_error}
                """
            )
        )


def rules():
    return [
        *collect_rules(),
        *pex.rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, HelmKubeParserLockfileSentinel),
    ]
