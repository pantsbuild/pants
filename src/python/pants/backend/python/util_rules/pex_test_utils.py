# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os.path
import zipfile
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Iterable, Iterator, Mapping

from pants.backend.python.target_types import MainSpecification, PexLayout
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import (
    Pex,
    PexPlatforms,
    PexProcess,
    PexRequest,
    VenvPex,
    VenvPexProcess,
)
from pants.backend.python.util_rules.pex_cli import PexPEX
from pants.backend.python.util_rules.pex_requirements import EntireLockfile, PexRequirements
from pants.engine.fs import Digest
from pants.engine.process import Process, ProcessResult
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.pip_requirement import PipRequirement
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class ExactRequirement:
    project_name: str
    version: str

    @classmethod
    def parse(cls, requirement: str) -> ExactRequirement:
        req = PipRequirement.parse(requirement)
        assert len(req.specs) == 1, softwrap(
            f"""
            Expected an exact requirement with only 1 specifier, given {requirement} with
            {len(req.specs)} specifiers
            """
        )
        operator, version = req.specs[0]
        assert operator == "==", softwrap(
            f"""
            Expected an exact requirement using only the '==' specifier, given {requirement}
            using the {operator!r} operator
            """
        )
        return cls(project_name=req.project_name, version=version)


def parse_requirements(requirements: Iterable[str]) -> Iterator[ExactRequirement]:
    for requirement in requirements:
        yield ExactRequirement.parse(requirement)


@dataclass(frozen=True)
class PexData:
    pex: Pex | VenvPex
    is_zipapp: bool
    sandbox_path: PurePath
    local_path: PurePath
    info: Mapping[str, Any]
    files: tuple[str, ...]


def get_all_data(rule_runner: RuleRunner, pex: Pex | VenvPex) -> PexData:
    # We fish PEX-INFO out of the pex manually rather than running PEX_TOOLS, as
    # we don't know if the pex can run on the current system.
    if isinstance(pex, VenvPex):
        digest = pex.digest
        sandbox_path = pex.pex_filename
    else:
        digest = pex.digest
        sandbox_path = pex.name

    rule_runner.scheduler.write_digest(digest)
    local_path = PurePath(rule_runner.build_root) / sandbox_path

    is_zipapp = zipfile.is_zipfile(local_path)
    if is_zipapp:
        with zipfile.ZipFile(local_path, "r") as zipfp:
            files = tuple(zipfp.namelist())
            pex_info_content = zipfp.read("PEX-INFO")
    else:
        files = tuple(
            os.path.normpath(os.path.relpath(os.path.join(root, path), local_path))
            for root, dirs, files in os.walk(local_path)
            for path in dirs + files
        )
        with open(os.path.join(local_path, "PEX-INFO"), "rb") as fp:
            pex_info_content = fp.read()

    return PexData(
        pex=pex,
        is_zipapp=is_zipapp,
        sandbox_path=PurePath(sandbox_path),
        local_path=local_path,
        info=json.loads(pex_info_content.decode()),
        files=files,
    )


def create_pex_and_get_all_data(
    rule_runner: RuleRunner,
    *,
    pex_type: type[Pex | VenvPex] = Pex,
    requirements: PexRequirements | EntireLockfile = PexRequirements(),
    main: MainSpecification | None = None,
    interpreter_constraints: InterpreterConstraints = InterpreterConstraints(),
    platforms: PexPlatforms = PexPlatforms(),
    sources: Digest | None = None,
    additional_inputs: Digest | None = None,
    additional_pants_args: tuple[str, ...] = (),
    additional_pex_args: tuple[str, ...] = (),
    env: Mapping[str, str] | None = None,
    internal_only: bool = True,
    layout: PexLayout | None = None,
) -> PexData:
    request = PexRequest(
        output_filename="test.pex",
        internal_only=internal_only,
        requirements=requirements,
        interpreter_constraints=interpreter_constraints,
        platforms=platforms,
        main=main,
        sources=sources,
        additional_inputs=additional_inputs,
        additional_args=additional_pex_args,
        layout=layout,
    )
    rule_runner.set_options(additional_pants_args, env=env, env_inherit=PYTHON_BOOTSTRAP_ENV)

    pex: Pex | VenvPex
    if pex_type == Pex:
        pex = rule_runner.request(Pex, [request])
    else:
        pex = rule_runner.request(VenvPex, [request])
    return get_all_data(rule_runner, pex)


def create_pex_and_get_pex_info(
    rule_runner: RuleRunner,
    *,
    pex_type: type[Pex | VenvPex] = Pex,
    requirements: PexRequirements | EntireLockfile = PexRequirements(),
    main: MainSpecification | None = None,
    interpreter_constraints: InterpreterConstraints = InterpreterConstraints(),
    platforms: PexPlatforms = PexPlatforms(),
    sources: Digest | None = None,
    additional_pants_args: tuple[str, ...] = (),
    additional_pex_args: tuple[str, ...] = (),
    internal_only: bool = True,
) -> Mapping[str, Any]:
    return create_pex_and_get_all_data(
        rule_runner,
        pex_type=pex_type,
        requirements=requirements,
        main=main,
        interpreter_constraints=interpreter_constraints,
        platforms=platforms,
        sources=sources,
        additional_pants_args=additional_pants_args,
        additional_pex_args=additional_pex_args,
        internal_only=internal_only,
    ).info


def rules():
    return [
        QueryRule(PexPEX, ()),
        QueryRule(Pex, (PexRequest,)),
        QueryRule(VenvPex, (PexRequest,)),
        QueryRule(Process, (PexProcess,)),
        QueryRule(Process, (VenvPexProcess,)),
        QueryRule(ProcessResult, (Process,)),
    ]
