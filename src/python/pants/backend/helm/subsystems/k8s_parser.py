# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import pkgutil
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from pants.backend.helm.utils.yaml import YamlPath
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import (
    VenvPex,
    VenvPexProcess,
    VenvPexRequest,
    create_venv_pex,
)
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import CreateDigest, FileContent, FileEntry
from pants.engine.intrinsics import create_digest, execute_process
from pants.engine.rules import collect_rules, implicitly, rule
from pants.option.option_types import StrOption
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize, softwrap

logger = logging.getLogger(__name__)

_HELM_K8S_PARSER_SOURCE = "k8s_parser_main.py"
_HELM_K8S_PARSER_PACKAGE = "pants.backend.helm.subsystems"


class HelmKubeParserSubsystem(PythonToolRequirementsBase):
    options_scope = "helm-k8s-parser"
    help_short = "Analyses K8S manifests rendered by Helm."

    default_requirements = [
        "hikaru>=1.1.0",
        "hikaru-model-28",
        "hikaru-model-27",
        "hikaru-model-26",
        "hikaru-model-25",
        "hikaru-model-24",
        "hikaru-model-23",
    ]

    register_interpreter_constraints = True

    crd = StrOption(
        help=softwrap(
            """
            Additional custom resource definitions be made available to all Helm processes
            or during value interpolation.
            """
        ),
        default="",
    )

    default_lockfile_resource = (_HELM_K8S_PARSER_PACKAGE, "k8s_parser.lock")


@dataclass(frozen=True)
class _HelmKubeParserTool:
    pex: VenvPex
    crd: str = ""


@rule
async def build_k8s_parser_tool(
    k8s_parser: HelmKubeParserSubsystem,
    pex_environment: PexEnvironment,
) -> _HelmKubeParserTool:
    parser_sources = pkgutil.get_data(_HELM_K8S_PARSER_PACKAGE, _HELM_K8S_PARSER_SOURCE)

    if not parser_sources:
        raise ValueError(
            f"Unable to find source to {_HELM_K8S_PARSER_SOURCE!r} in {_HELM_K8S_PARSER_PACKAGE}"
        )

    parser_file_content = FileContent(
        path="__k8s_parser.py", content=parser_sources, is_executable=True
    )

    digest_sources = [parser_file_content]
    if k8s_parser.crd != "":
        crd_sources = open(k8s_parser.crd, "rb").read()
        if not crd_sources:
            raise ValueError(f"Unable to find source to crd_cron in {_HELM_K8S_PARSER_PACKAGE}")
        parser_file_content_source = FileContent(
            path="__crd_source.py", content=crd_sources, is_executable=False
        )
        digest_sources.append(parser_file_content_source)
    parser_digest = await create_digest(CreateDigest(digest_sources))

    # We use copies of site packages because hikaru gets confused with symlinked packages
    # The core hikaru package tries to load the packages containing the kubernetes-versioned models
    # using the __path__ attribute of the core package,
    # which doesn't work when the packages are symlinked from inside the namespace-handling dirs in the PEX
    use_site_packages_copies = True

    parser_pex = await create_venv_pex(
        VenvPexRequest(
            k8s_parser.to_pex_request(
                main=EntryPoint(PurePath(parser_file_content.path).stem),
                sources=parser_digest,
            ),
            pex_environment.in_sandbox(working_directory=None),
            site_packages_copies=use_site_packages_copies,
        ),
        **implicitly(),
    )
    return _HelmKubeParserTool(parser_pex, k8s_parser.crd)


@dataclass(frozen=True)
class ParseKubeManifestRequest(EngineAwareParameter):
    file: FileEntry

    def debug_hint(self) -> str | None:
        return self.file.path

    def metadata(self) -> dict[str, Any] | None:
        return {"file": self.file}


@dataclass(frozen=True)
class ParsedImageRefEntry:
    document_index: int
    path: YamlPath
    unparsed_image_ref: str


@dataclass(frozen=True)
class ParsedKubeManifest(EngineAwareReturnType):
    filename: str
    found_image_refs: tuple[ParsedImageRefEntry, ...]

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
    file_digest = await create_digest(CreateDigest([request.file]))

    result = await execute_process(
        **implicitly(
            VenvPexProcess(
                tool.pex,
                argv=[request.file.path, tool.crd],
                input_digest=file_digest,
                description=f"Analyzing Kubernetes manifest {request.file.path}",
                level=LogLevel.DEBUG,
            )
        )
    )

    if result.exit_code == 0:
        output = result.stdout.decode("utf-8").splitlines()
        image_refs: list[ParsedImageRefEntry] = []
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

            image_refs.append(
                ParsedImageRefEntry(
                    document_index=int(parts[0]),
                    path=YamlPath.parse(parts[1]),
                    unparsed_image_ref=parts[2],
                )
            )

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
    ]
