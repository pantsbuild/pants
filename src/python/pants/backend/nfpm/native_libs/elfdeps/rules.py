# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import PurePath

from pants.backend.nfpm.native_libs.elfdeps.subsystem import rules as subsystem_rules
from pants.backend.nfpm.native_libs.elfdeps.subsystem import setup_elfdeps_analyze_tool
from pants.backend.python.util_rules.pex import Pex, PexProcess, VenvPexProcess
from pants.backend.python.util_rules.pex_cli import PexPEX
from pants.core.util_rules.system_binaries import UnzipBinary
from pants.engine.process import Process, ProcessResult, execute_process_or_raise
from pants.engine.rules import Rule, collect_rules, concurrently, implicitly, rule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class RequestPexELFInfo:
    target_pex: Pex


@dataclass(frozen=True, order=True)
class SOInfo:  # elfdeps should not be used in rules, so this holds the same data as elfdeps.SOInfo.
    soname: str
    version: str
    marker: str
    # so_info combines soname+version+marker using whatever standard elfdeps follows.
    so_info: str = dataclass_field(compare=False)


@dataclass(frozen=True)
class PexELFInfo:
    provides: tuple[SOInfo, ...]
    requires: tuple[SOInfo, ...]

    def __init__(
        self, provides: Iterable[Mapping[str, str]], requires: Iterable[Mapping[str, str]]
    ):
        object.__setattr__(
            self, "provides", tuple(sorted({SOInfo(**so_info) for so_info in provides}))
        )
        object.__setattr__(
            self, "requires", tuple(sorted({SOInfo(**so_info) for so_info in requires}))
        )


@rule(
    desc="Analyze ELF (native lib) dependencies of wheels and files in a PEX",
    level=LogLevel.DEBUG,
)
async def elfdeps_analyze_pex(
    request: RequestPexELFInfo, pex_pex: PexPEX, unzip: UnzipBinary
) -> PexELFInfo:
    wheel_repo_dir = str(PurePath(request.target_pex.name).with_suffix(".wheel_repo"))
    contents_dir = str(PurePath(request.target_pex.name).with_suffix(".wheel_repo"))

    extracted_wheels, extracted_files, elfdeps_analyze_tool = await concurrently(
        execute_process_or_raise(
            **implicitly(
                PexProcess(
                    pex=Pex(
                        digest=pex_pex.digest,
                        name=pex_pex.exe,
                        python=request.target_pex.python,
                    ),
                    argv=[
                        request.target_pex.name,
                        "repository",
                        "extract",
                        "--dest-dir",
                        wheel_repo_dir,
                    ],
                    input_digest=request.target_pex.digest,
                    output_directories=(wheel_repo_dir,),
                    extra_env={"PEX_MODULE": "pex.tools"},
                    description=f"Extract wheels from {request.target_pex.name}",
                    level=LogLevel.DEBUG,
                )
            )
        ),
        execute_process_or_raise(
            **implicitly(
                # pex-tools can only extract wheels and PEX-INFO,
                # so unzip remaining files from pex manually
                # (even though that means relying on pex implementation details)
                Process(
                    argv=[
                        unzip.path,
                        request.target_pex.name,
                        "-x",  # exclude wheels
                        ".deps/*",  # this ties us to this pex implementation detail :(
                        "-d",
                        wheel_repo_dir,
                    ],
                    input_digest=request.target_pex.digest,
                    output_directories=(contents_dir,),
                    description=f"Extract non-wheel files from {request.target_pex.name}",
                    level=LogLevel.DEBUG,
                ),
            )
        ),
        setup_elfdeps_analyze_tool(**implicitly()),
    )

    process_results: tuple[ProcessResult, ProcessResult] = await concurrently(
        execute_process_or_raise(
            **implicitly(
                VenvPexProcess(
                    elfdeps_analyze_tool.pex,
                    argv=("--mode", "wheels", wheel_repo_dir),
                    input_digest=extracted_wheels.output_digest,
                    description=f"Calculate ELF provides+requires for wheels in pex {request.target_pex.name}",
                    level=LogLevel.DEBUG,
                )
            )
        ),
        execute_process_or_raise(
            **implicitly(
                VenvPexProcess(
                    elfdeps_analyze_tool.pex,
                    argv=("--mode", "files", contents_dir),
                    input_digest=extracted_files.output_digest,
                    description=f"Calculate ELF provides+requires for non-wheel files in pex {request.target_pex.name}",
                    level=LogLevel.DEBUG,
                )
            )
        ),
    )

    pex_elf_info: dict[str, list[dict[str, str]]] = {"provides": [], "requires": []}
    for process_result in process_results:
        result = json.loads(process_result.stdout)
        pex_elf_info["provides"].extend(result["provides"])
        pex_elf_info["requires"].extend(result["requires"])

    return PexELFInfo(
        provides=pex_elf_info["provides"],
        requires=pex_elf_info["requires"],
    )


def rules() -> Iterable[Rule]:
    return (
        *subsystem_rules(),
        *collect_rules(),
    )
