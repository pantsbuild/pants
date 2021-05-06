# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os.path
import textwrap
import zipfile
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, Mapping, Tuple, cast

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pkg_resources import Requirement

from pants.backend.python.target_types import EntryPoint, MainSpecification
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import (
    Pex,
    PexDistributionInfo,
    PexPlatforms,
    PexProcess,
    PexRequest,
    PexRequirements,
    PexResolveInfo,
    VenvPex,
    VenvPexProcess,
)
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex_cli import PexPEX
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.process import Process, ProcessResult
from pants.testutil.rule_runner import QueryRule, RuleRunner


@dataclass(frozen=True)
class ExactRequirement:
    project_name: str
    version: str

    @classmethod
    def parse(cls, requirement: str) -> ExactRequirement:
        req = Requirement.parse(requirement)
        assert len(req.specs) == 1, (
            f"Expected an exact requirement with only 1 specifier, given {requirement} with "
            f"{len(req.specs)} specifiers"
        )
        operator, version = req.specs[0]
        assert operator == "==", (
            f"Expected an exact requirement using only the '==' specifier, given {requirement} "
            f"using the {operator!r} operator"
        )
        return cls(project_name=req.project_name, version=version)


def parse_requirements(requirements: Iterable[str]) -> Iterator[ExactRequirement]:
    for requirement in requirements:
        yield ExactRequirement.parse(requirement)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *pex_rules(),
            QueryRule(Pex, (PexRequest,)),
            QueryRule(VenvPex, (PexRequest,)),
            QueryRule(Process, (PexProcess,)),
            QueryRule(Process, (VenvPexProcess,)),
            QueryRule(ProcessResult, (Process,)),
            QueryRule(PexResolveInfo, (Pex,)),
            QueryRule(PexResolveInfo, (VenvPex,)),
            QueryRule(PexPEX, ()),
        ]
    )


def create_pex_and_get_all_data(
    rule_runner: RuleRunner,
    *,
    pex_type: type[Pex | VenvPex] = Pex,
    requirements: PexRequirements = PexRequirements(),
    main: MainSpecification | None = None,
    interpreter_constraints: InterpreterConstraints = InterpreterConstraints(),
    platforms: PexPlatforms = PexPlatforms(),
    sources: Digest | None = None,
    additional_inputs: Digest | None = None,
    additional_pants_args: Tuple[str, ...] = (),
    additional_pex_args: Tuple[str, ...] = (),
    env: Mapping[str, str] | None = None,
    internal_only: bool = True,
) -> Dict:
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
    )
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python", *additional_pants_args],
        env=env,
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    pex = rule_runner.request(pex_type, [request])
    if isinstance(pex, Pex):
        digest = pex.digest
        pex_pex = rule_runner.request(PexPEX, [])
        process = rule_runner.request(
            Process,
            [
                PexProcess(
                    Pex(digest=pex_pex.digest, name=pex_pex.exe, python=pex.python),
                    argv=["-m", "pex.tools", pex.name, "info"],
                    input_digest=pex.digest,
                    extra_env=dict(PEX_INTERPRETER="1"),
                    description="Extract PEX-INFO.",
                )
            ],
        )
    elif isinstance(pex, VenvPex):
        digest = pex.digest
        process = rule_runner.request(
            Process,
            [
                VenvPexProcess(
                    pex,
                    argv=["info"],
                    extra_env=dict(PEX_TOOLS="1"),
                    description="Extract PEX-INFO.",
                ),
            ],
        )
    else:
        raise AssertionError(f"Expected a Pex or a VenvPex but got a {type(pex)}.")

    rule_runner.scheduler.write_digest(digest)
    pex_path = os.path.join(rule_runner.build_root, "test.pex")
    result = rule_runner.request(ProcessResult, [process])
    pex_info_content = result.stdout.decode()

    with zipfile.ZipFile(pex_path, "r") as zipfp:
        pex_list = zipfp.namelist()

    return {
        "pex": pex,
        "local_path": pex_path,
        "info": json.loads(pex_info_content),
        "files": pex_list,
    }


def create_pex_and_get_pex_info(
    rule_runner: RuleRunner,
    *,
    pex_type: type[Pex | VenvPex] = Pex,
    requirements: PexRequirements = PexRequirements(),
    main: MainSpecification | None = None,
    interpreter_constraints: InterpreterConstraints = InterpreterConstraints(),
    platforms: PexPlatforms = PexPlatforms(),
    sources: Digest | None = None,
    additional_pants_args: Tuple[str, ...] = (),
    additional_pex_args: Tuple[str, ...] = (),
    internal_only: bool = True,
) -> Dict:
    return cast(
        Dict,
        create_pex_and_get_all_data(
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
        )["info"],
    )


def test_pex_execution(rule_runner: RuleRunner) -> None:
    sources = rule_runner.request(
        Digest,
        [
            CreateDigest(
                (
                    FileContent("main.py", b'print("from main")'),
                    FileContent("subdir/sub.py", b'print("from sub")'),
                )
            ),
        ],
    )
    pex_output = create_pex_and_get_all_data(rule_runner, main=EntryPoint("main"), sources=sources)

    pex_files = pex_output["files"]
    assert "pex" not in pex_files
    assert "main.py" in pex_files
    assert "subdir/sub.py" in pex_files

    # This should run the Pex using the same interpreter used to create it. We must set the `PATH` so that the shebang
    # works.
    process = Process(
        argv=("./test.pex",),
        env={"PATH": os.getenv("PATH", "")},
        input_digest=pex_output["pex"].digest,
        description="Run the pex and make sure it works",
    )
    result = rule_runner.request(ProcessResult, [process])
    assert result.stdout == b"from main\n"


@pytest.mark.parametrize("pex_type", [Pex, VenvPex])
def test_pex_environment(rule_runner: RuleRunner, pex_type: type[Pex | VenvPex]) -> None:
    sources = rule_runner.request(
        Digest,
        [
            CreateDigest(
                (
                    FileContent(
                        path="main.py",
                        content=textwrap.dedent(
                            """
                            from os import environ
                            print(f"LANG={environ.get('LANG')}")
                            print(f"ftp_proxy={environ.get('ftp_proxy')}")
                            """
                        ).encode(),
                    ),
                )
            ),
        ],
    )
    pex_output = create_pex_and_get_all_data(
        rule_runner,
        pex_type=pex_type,
        main=EntryPoint("main"),
        sources=sources,
        additional_pants_args=(
            "--subprocess-environment-env-vars=LANG",  # Value should come from environment.
            "--subprocess-environment-env-vars=ftp_proxy=dummyproxy",
        ),
        interpreter_constraints=InterpreterConstraints(["CPython>=3.6"]),
        env={"LANG": "es_PY.UTF-8"},
    )

    pex = pex_output["pex"]
    pex_process_type = PexProcess if isinstance(pex, Pex) else VenvPexProcess
    process = rule_runner.request(
        Process,
        [
            pex_process_type(
                pex,
                description="Run the pex and check its reported environment",
            ),
        ],
    )

    result = rule_runner.request(ProcessResult, [process])
    assert b"LANG=es_PY.UTF-8" in result.stdout
    assert b"ftp_proxy=dummyproxy" in result.stdout


def test_resolves_dependencies(rule_runner: RuleRunner) -> None:
    requirements = PexRequirements(["six==1.12.0", "jsonschema==2.6.0", "requests==2.23.0"])
    pex_info = create_pex_and_get_pex_info(rule_runner, requirements=requirements)
    # NB: We do not check for transitive dependencies, which PEX-INFO will include. We only check
    # that at least the dependencies we requested are included.
    assert set(parse_requirements(requirements)).issubset(
        set(parse_requirements(pex_info["requirements"]))
    )


def test_requirement_constraints(rule_runner: RuleRunner) -> None:
    direct_deps = ["requests>=1.0.0,<=2.23.0"]

    def assert_direct_requirements(pex_info):
        assert set(Requirement.parse(r) for r in pex_info["requirements"]) == set(
            Requirement.parse(d) for d in direct_deps
        )

    # Unconstrained, we should always pick the top of the range (requests 2.23.0) since the top of
    # the range is a transitive closure over universal wheels.
    direct_pex_info = create_pex_and_get_pex_info(
        rule_runner, requirements=PexRequirements(direct_deps)
    )
    assert_direct_requirements(direct_pex_info)
    assert {
        "certifi-2020.12.5-py2.py3-none-any.whl",
        "chardet-3.0.4-py2.py3-none-any.whl",
        "idna-2.10-py2.py3-none-any.whl",
        "requests-2.23.0-py2.py3-none-any.whl",
        "urllib3-1.25.11-py2.py3-none-any.whl",
    } == set(direct_pex_info["distributions"].keys())

    constraints = ["requests==2.0.0"]
    rule_runner.create_file("constraints.txt", "\n".join(constraints))
    constrained_pex_info = create_pex_and_get_pex_info(
        rule_runner,
        requirements=PexRequirements(direct_deps),
        additional_pants_args=("--python-setup-requirement-constraints=constraints.txt",),
    )
    assert_direct_requirements(constrained_pex_info)
    assert {"requests-2.0.0-py2.py3-none-any.whl"} == set(
        constrained_pex_info["distributions"].keys()
    )


def test_entry_point(rule_runner: RuleRunner) -> None:
    entry_point = "pydoc"
    pex_info = create_pex_and_get_pex_info(rule_runner, main=EntryPoint(entry_point))
    assert pex_info["entry_point"] == entry_point


def test_interpreter_constraints(rule_runner: RuleRunner) -> None:
    constraints = InterpreterConstraints(["CPython>=2.7,<3", "CPython>=3.6"])
    pex_info = create_pex_and_get_pex_info(
        rule_runner, interpreter_constraints=constraints, internal_only=False
    )
    assert set(pex_info["interpreter_constraints"]) == {str(c) for c in constraints}


def test_additional_args(rule_runner: RuleRunner) -> None:
    pex_info = create_pex_and_get_pex_info(rule_runner, additional_pex_args=("--not-zip-safe",))
    assert pex_info["zip_safe"] is False


def test_platforms(rule_runner: RuleRunner) -> None:
    # We use Python 2.7, rather than Python 3, to ensure that the specified platform is
    # actually used.
    platforms = PexPlatforms(["linux-x86_64-cp-27-cp27mu"])
    constraints = InterpreterConstraints(["CPython>=2.7,<3", "CPython>=3.6"])
    pex_output = create_pex_and_get_all_data(
        rule_runner,
        requirements=PexRequirements(["cryptography==2.9"]),
        platforms=platforms,
        interpreter_constraints=constraints,
        internal_only=False,  # Internal only PEXes do not support (foreign) platforms.
    )
    assert any(
        "cryptography-2.9-cp27-cp27mu-manylinux2010_x86_64.whl" in fp for fp in pex_output["files"]
    )
    assert not any("cryptography-2.9-cp27-cp27m-" in fp for fp in pex_output["files"])
    assert not any("cryptography-2.9-cp35-abi3" in fp for fp in pex_output["files"])

    # NB: Platforms override interpreter constraints.
    assert pex_output["info"]["interpreter_constraints"] == []


def test_additional_inputs(rule_runner: RuleRunner) -> None:
    # We use pex's --preamble-file option to set a custom preamble from a file.
    # This verifies that the file was indeed provided as additional input to the pex call.
    preamble_file = "custom_preamble.txt"
    preamble = "#!CUSTOM PREAMBLE\n"
    additional_inputs = rule_runner.request(
        Digest, [CreateDigest([FileContent(path=preamble_file, content=preamble.encode())])]
    )
    additional_pex_args = (f"--preamble-file={preamble_file}",)
    pex_output = create_pex_and_get_all_data(
        rule_runner, additional_inputs=additional_inputs, additional_pex_args=additional_pex_args
    )
    with zipfile.ZipFile(pex_output["local_path"], "r") as zipfp:
        with zipfp.open("__main__.py", "r") as main:
            main_content = main.read().decode()
    assert main_content[: len(preamble)] == preamble


@pytest.mark.parametrize("pex_type", [Pex, VenvPex])
def test_venv_pex_resolve_info(rule_runner: RuleRunner, pex_type: type[Pex | VenvPex]) -> None:
    venv_pex = create_pex_and_get_all_data(
        rule_runner, pex_type=pex_type, requirements=PexRequirements(["requests==2.23.0"])
    )["pex"]
    dists = rule_runner.request(PexResolveInfo, [venv_pex])
    assert dists[0] == PexDistributionInfo("certifi", Version("2020.12.5"), None, ())
    assert dists[1] == PexDistributionInfo("chardet", Version("3.0.4"), None, ())
    assert dists[2] == PexDistributionInfo(
        "idna", Version("2.10"), SpecifierSet("!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,>=2.7"), ()
    )
    assert dists[3].project_name == "requests"
    assert dists[3].version == Version("2.23.0")
    assert Requirement.parse('PySocks!=1.5.7,>=1.5.6; extra == "socks"') in dists[3].requires_dists
    assert dists[4].project_name == "urllib3"
