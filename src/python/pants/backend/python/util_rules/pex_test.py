# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os.path
import re
import textwrap
import zipfile
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Iterable, Iterator, Mapping

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pkg_resources import Requirement

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.target_types import EntryPoint, MainSpecification
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadata
from pants.backend.python.util_rules.pex import (
    Pex,
    PexDistributionInfo,
    PexPlatforms,
    PexProcess,
    PexRequest,
    PexResolveInfo,
    VenvPex,
    VenvPexProcess,
    _build_pex_description,
)
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex_cli import PexPEX
from pants.backend.python.util_rules.pex_requirements import (
    Lockfile,
    LockfileContent,
    PexRequirements,
)
from pants.core.util_rules.lockfile_metadata import InvalidLockfileError
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, Directory, FileContent
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.option.global_options import GlobalOptions
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error
from pants.util.dirutil import safe_rmtree
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class ExactRequirement:
    project_name: str
    version: str

    @classmethod
    def parse(cls, requirement: str) -> ExactRequirement:
        req = PipRequirement.parse(requirement)
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
            QueryRule(GlobalOptions, []),
            QueryRule(Pex, (PexRequest,)),
            QueryRule(VenvPex, (PexRequest,)),
            QueryRule(Process, (PexProcess,)),
            QueryRule(Process, (VenvPexProcess,)),
            QueryRule(ProcessResult, (Process,)),
            QueryRule(PexResolveInfo, (Pex,)),
            QueryRule(PexResolveInfo, (VenvPex,)),
            QueryRule(PexPEX, ()),
        ],
    )


@dataclass(frozen=True)
class PexData:
    pex: Pex | VenvPex
    is_zipapp: bool
    sandbox_path: PurePath
    local_path: PurePath
    info: Mapping[str, Any]
    files: tuple[str, ...]


def create_pex_and_get_all_data(
    rule_runner: RuleRunner,
    *,
    pex_type: type[Pex | VenvPex] = Pex,
    requirements: PexRequirements | Lockfile | LockfileContent = PexRequirements(),
    main: MainSpecification | None = None,
    interpreter_constraints: InterpreterConstraints = InterpreterConstraints(),
    platforms: PexPlatforms = PexPlatforms(),
    sources: Digest | None = None,
    additional_inputs: Digest | None = None,
    additional_pants_args: tuple[str, ...] = (),
    additional_pex_args: tuple[str, ...] = (),
    env: Mapping[str, str] | None = None,
    internal_only: bool = True,
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
    )
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python", *additional_pants_args],
        env=env,
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )

    pex: Pex | VenvPex
    if pex_type == Pex:
        pex = rule_runner.request(Pex, [request])
        digest = pex.digest
        sandbox_path = pex.name
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
    else:
        pex = rule_runner.request(VenvPex, [request])
        digest = pex.digest
        sandbox_path = pex.pex_filename
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

    rule_runner.scheduler.write_digest(digest)
    local_path = PurePath(rule_runner.build_root) / "test.pex"
    result = rule_runner.request(ProcessResult, [process])
    pex_info_content = result.stdout.decode()

    is_zipapp = zipfile.is_zipfile(local_path)
    if is_zipapp:
        with zipfile.ZipFile(local_path, "r") as zipfp:
            files = tuple(zipfp.namelist())
    else:
        files = tuple(
            os.path.normpath(os.path.relpath(os.path.join(root, path), local_path))
            for root, dirs, files in os.walk(local_path)
            for path in dirs + files
        )

    return PexData(
        pex=pex,
        is_zipapp=is_zipapp,
        sandbox_path=PurePath(sandbox_path),
        local_path=local_path,
        info=json.loads(pex_info_content),
        files=files,
    )


def create_pex_and_get_pex_info(
    rule_runner: RuleRunner,
    *,
    pex_type: type[Pex | VenvPex] = Pex,
    requirements: PexRequirements | Lockfile | LockfileContent = PexRequirements(),
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


@pytest.mark.parametrize("pex_type", [Pex, VenvPex])
@pytest.mark.parametrize("internal_only", [True, False])
def test_pex_execution(
    rule_runner: RuleRunner, pex_type: type[Pex | VenvPex], internal_only: bool
) -> None:
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
    pex_data = create_pex_and_get_all_data(
        rule_runner,
        pex_type=pex_type,
        internal_only=internal_only,
        main=EntryPoint("main"),
        sources=sources,
    )

    assert "pex" not in pex_data.files
    assert "main.py" in pex_data.files
    assert "subdir/sub.py" in pex_data.files

    # This should run the Pex using the same interpreter used to create it. We must set the `PATH`
    # so that the shebang works.
    pex_exe = (
        f"./{pex_data.sandbox_path}"
        if pex_data.is_zipapp
        else os.path.join(pex_data.sandbox_path, "__main__.py")
    )
    process = Process(
        argv=(pex_exe,),
        env={"PATH": os.getenv("PATH", "")},
        input_digest=pex_data.pex.digest,
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
    pex_data = create_pex_and_get_all_data(
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

    pex_process_type = PexProcess if isinstance(pex_data.pex, Pex) else VenvPexProcess
    process = rule_runner.request(
        Process,
        [
            pex_process_type(
                pex_data.pex,
                description="Run the pex and check its reported environment",
            ),
        ],
    )

    result = rule_runner.request(ProcessResult, [process])
    assert b"LANG=es_PY.UTF-8" in result.stdout
    assert b"ftp_proxy=dummyproxy" in result.stdout


@pytest.mark.parametrize("pex_type", [Pex, VenvPex])
def test_pex_working_directory(rule_runner: RuleRunner, pex_type: type[Pex | VenvPex]) -> None:
    named_caches_dir = rule_runner.request(GlobalOptions, []).named_caches_dir
    sources = rule_runner.request(
        Digest,
        [
            CreateDigest(
                (
                    FileContent(
                        path="main.py",
                        content=textwrap.dedent(
                            """
                            import os
                            cwd = os.getcwd()
                            print(f"CWD: {cwd}")
                            for path, dirs, _ in os.walk(cwd):
                                for name in dirs:
                                    print(f"DIR: {os.path.relpath(os.path.join(path, name), cwd)}")
                            """
                        ).encode(),
                    ),
                )
            ),
        ],
    )

    pex_data = create_pex_and_get_all_data(
        rule_runner,
        pex_type=pex_type,
        main=EntryPoint("main"),
        sources=sources,
        interpreter_constraints=InterpreterConstraints(["CPython>=3.6"]),
    )

    pex_process_type = PexProcess if isinstance(pex_data.pex, Pex) else VenvPexProcess

    dirpath = "foo/bar/baz"
    runtime_files = rule_runner.request(Digest, [CreateDigest([Directory(path=dirpath)])])

    dirpath_parts = os.path.split(dirpath)
    for i in range(0, len(dirpath_parts)):
        working_dir = os.path.join(*dirpath_parts[:i]) if i > 0 else None
        expected_subdir = os.path.join(*dirpath_parts[i:]) if i < len(dirpath_parts) else None
        process = rule_runner.request(
            Process,
            [
                pex_process_type(
                    pex_data.pex,
                    description="Run the pex and check its cwd",
                    working_directory=working_dir,
                    input_digest=runtime_files,
                    # We skip the process cache for this PEX to ensure that it re-runs.
                    cache_scope=ProcessCacheScope.PER_SESSION,
                )
            ],
        )

        # For VenvPexes, run the PEX twice while clearing the venv dir in between. This emulates
        # situations where a PEX creation hits the process cache, while venv seeding misses the PEX
        # cache.
        if isinstance(pex_data.pex, VenvPex):
            # Request once to ensure that the directory is seeded, and then start a new session so
            # that the second run happens as well.
            _ = rule_runner.request(ProcessResult, [process])
            rule_runner.new_session("re-run-for-venv-pex")
            rule_runner.set_options(
                ["--backend-packages=pants.backend.python"],
                env_inherit={"PATH", "PYENV_ROOT", "HOME"},
            )

            # Clear the cache.
            venv_dir = os.path.join(named_caches_dir, "pex_root", pex_data.pex.venv_rel_dir)
            assert os.path.isdir(venv_dir)
            safe_rmtree(venv_dir)

        result = rule_runner.request(ProcessResult, [process])
        output_str = result.stdout.decode()
        mo = re.search(r"CWD: (.*)\n", output_str)
        assert mo is not None
        reported_cwd = mo.group(1)
        if working_dir:
            assert reported_cwd.endswith(working_dir)
        if expected_subdir:
            assert f"DIR: {expected_subdir}" in output_str


def test_resolves_dependencies(rule_runner: RuleRunner) -> None:
    requirements = PexRequirements(["six==1.12.0", "jsonschema==2.6.0", "requests==2.23.0"])
    pex_info = create_pex_and_get_pex_info(rule_runner, requirements=requirements)
    # NB: We do not check for transitive dependencies, which PEX-INFO will include. We only check
    # that at least the dependencies we requested are included.
    assert set(parse_requirements(requirements.req_strings)).issubset(
        set(parse_requirements(pex_info["requirements"]))
    )


@pytest.mark.parametrize("is_all_constraints_resolve", [True, False])
@pytest.mark.parametrize("internal_only", [True, False])
def test_use_packed_pex_requirements(
    rule_runner: RuleRunner, is_all_constraints_resolve: bool, internal_only: bool
) -> None:
    requirements = PexRequirements(
        ["six==1.12.0"], is_all_constraints_resolve=is_all_constraints_resolve
    )
    pex_data = create_pex_and_get_all_data(
        rule_runner, requirements=requirements, internal_only=internal_only
    )
    # If this is either internal_only, or an all_constraints resolve, we should use packed.
    should_use_packed = is_all_constraints_resolve or internal_only
    assert (not pex_data.is_zipapp) == should_use_packed


def test_requirement_constraints(rule_runner: RuleRunner) -> None:
    direct_deps = ["requests>=1.0.0,<=2.23.0"]

    def assert_direct_requirements(pex_info):
        assert {PipRequirement.parse(r) for r in pex_info["requirements"]} == {
            PipRequirement.parse(d) for d in direct_deps
        }

    # Unconstrained, we should always pick the top of the range (requests 2.23.0) since the top of
    # the range is a transitive closure over universal wheels.
    direct_pex_info = create_pex_and_get_pex_info(
        rule_runner, requirements=PexRequirements(direct_deps)
    )
    assert_direct_requirements(direct_pex_info)
    assert "requests-2.23.0-py2.py3-none-any.whl" in set(direct_pex_info["distributions"].keys())

    constraints = [
        "requests==2.16.0",
        "certifi==2019.6.16",
        "chardet==3.0.2",
        "idna==2.5",
        "urllib3==1.21.1",
    ]
    rule_runner.write_files({"constraints.txt": "\n".join(constraints)})
    constrained_pex_info = create_pex_and_get_pex_info(
        rule_runner,
        requirements=PexRequirements(direct_deps, constraints_strings=constraints),
        additional_pants_args=("--python-requirement-constraints=constraints.txt",),
    )
    assert_direct_requirements(constrained_pex_info)
    assert {
        "certifi-2019.6.16-py2.py3-none-any.whl",
        "chardet-3.0.2-py2.py3-none-any.whl",
        "idna-2.5-py2.py3-none-any.whl",
        "requests-2.16.0-py2.py3-none-any.whl",
        "urllib3-1.21.1-py2.py3-none-any.whl",
    } == set(constrained_pex_info["distributions"].keys())


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
    pex_info = create_pex_and_get_pex_info(rule_runner, additional_pex_args=("--no-strip-pex-env",))
    assert pex_info["strip_pex_env"] is False


def test_platforms(rule_runner: RuleRunner) -> None:
    # We use Python 2.7, rather than Python 3, to ensure that the specified platform is
    # actually used.
    platforms = PexPlatforms(["linux-x86_64-cp-27-cp27mu"])
    constraints = InterpreterConstraints(["CPython>=2.7,<3", "CPython>=3.6"])
    pex_data = create_pex_and_get_all_data(
        rule_runner,
        requirements=PexRequirements(["cryptography==2.9"]),
        platforms=platforms,
        interpreter_constraints=constraints,
        internal_only=False,  # Internal only PEXes do not support (foreign) platforms.
    )
    assert any(
        "cryptography-2.9-cp27-cp27mu-manylinux2010_x86_64.whl" in fp for fp in pex_data.files
    )
    assert not any("cryptography-2.9-cp27-cp27m-" in fp for fp in pex_data.files)
    assert not any("cryptography-2.9-cp35-abi3" in fp for fp in pex_data.files)

    # NB: Platforms override interpreter constraints.
    assert pex_data.info["interpreter_constraints"] == []


@pytest.mark.parametrize("pex_type", [Pex, VenvPex])
@pytest.mark.parametrize("internal_only", [True, False])
def test_additional_inputs(
    rule_runner: RuleRunner, pex_type: type[Pex | VenvPex], internal_only: bool
) -> None:
    # We use Pex's --sources-directory option to add an extra source file to the PEX.
    # This verifies that the file was indeed provided as additional input to the pex call.
    extra_src_dir = "extra_src"
    data_file = os.path.join("data", "file")
    data = "42"
    additional_inputs = rule_runner.request(
        Digest,
        [
            CreateDigest(
                [FileContent(path=os.path.join(extra_src_dir, data_file), content=data.encode())]
            )
        ],
    )
    additional_pex_args = ("--sources-directory", extra_src_dir)
    pex_data = create_pex_and_get_all_data(
        rule_runner,
        pex_type=pex_type,
        internal_only=internal_only,
        additional_inputs=additional_inputs,
        additional_pex_args=additional_pex_args,
    )
    if pex_data.is_zipapp:
        with zipfile.ZipFile(pex_data.local_path, "r") as zipfp:
            with zipfp.open(data_file, "r") as datafp:
                data_file_content = datafp.read()
    else:
        with open(pex_data.local_path / data_file, "rb") as datafp:
            data_file_content = datafp.read()
    assert data == data_file_content.decode()


@pytest.mark.parametrize("pex_type", [Pex, VenvPex])
def test_venv_pex_resolve_info(rule_runner: RuleRunner, pex_type: type[Pex | VenvPex]) -> None:
    constraints = [
        "requests==2.23.0",
        "certifi==2020.12.5",
        "chardet==3.0.4",
        "idna==2.10",
        "urllib3==1.25.11",
    ]
    rule_runner.write_files({"constraints.txt": "\n".join(constraints)})
    pex = create_pex_and_get_all_data(
        rule_runner,
        pex_type=pex_type,
        requirements=PexRequirements(["requests==2.23.0"], constraints_strings=constraints),
        additional_pants_args=("--python-requirement-constraints=constraints.txt",),
    ).pex
    dists = rule_runner.request(PexResolveInfo, [pex])
    assert dists[0] == PexDistributionInfo("certifi", Version("2020.12.5"), None, ())
    assert dists[1] == PexDistributionInfo("chardet", Version("3.0.4"), None, ())
    assert dists[2] == PexDistributionInfo(
        "idna", Version("2.10"), SpecifierSet("!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,>=2.7"), ()
    )
    assert dists[3].project_name == "requests"
    assert dists[3].version == Version("2.23.0")
    # requires_dists is parsed from metadata written by the pex tool, and is always
    #   a set of valid pkg_resources.Requirements.
    assert Requirement.parse('PySocks!=1.5.7,>=1.5.6; extra == "socks"') in dists[3].requires_dists
    assert dists[4].project_name == "urllib3"


def test_build_pex_description() -> None:
    def assert_description(
        requirements: PexRequirements | Lockfile | LockfileContent,
        *,
        description: str | None = None,
        expected: str,
    ) -> None:
        request = PexRequest(
            output_filename="new.pex",
            internal_only=True,
            requirements=requirements,
            description=description,
        )
        assert _build_pex_description(request) == expected

    repo_pex = Pex(EMPTY_DIGEST, "repo.pex", None)

    assert_description(PexRequirements(), description="Custom!", expected="Custom!")
    assert_description(
        PexRequirements(repository_pex=repo_pex), description="Custom!", expected="Custom!"
    )

    assert_description(PexRequirements(), expected="Building new.pex")
    assert_description(PexRequirements(repository_pex=repo_pex), expected="Building new.pex")

    assert_description(
        PexRequirements(["req"]), expected="Building new.pex with 1 requirement: req"
    )
    assert_description(
        PexRequirements(["req"], repository_pex=repo_pex),
        expected="Extracting 1 requirement to build new.pex from repo.pex: req",
    )

    assert_description(
        PexRequirements(["req1", "req2"]),
        expected="Building new.pex with 2 requirements: req1, req2",
    )
    assert_description(
        PexRequirements(["req1", "req2"], repository_pex=repo_pex),
        expected="Extracting 2 requirements to build new.pex from repo.pex: req1, req2",
    )

    assert_description(
        LockfileContent(
            file_content=FileContent("lock.txt", b""),
            resolve_name="a",
            req_strings=FrozenOrderedSet(),
        ),
        expected="Building new.pex from lock.txt",
    )

    assert_description(
        Lockfile(
            file_path="lock.txt",
            file_path_description_of_origin="foo",
            resolve_name="a",
            req_strings=FrozenOrderedSet(),
        ),
        expected="Building new.pex from lock.txt",
    )


def test_lockfile_validation(rule_runner: RuleRunner) -> None:
    """Check that we properly load and validate lockfile metadata for both types of locks.

    Note that we don't exhaustively test every source of lockfile failure nor the different options
    for `--invalid-lockfile-behavior`, as those are already tested in pex_requirements_test.py.
    """

    # We create a lockfile that claims it works with no requirements. It should fail when we try
    # to build a PEX with a requirement.
    lock_content = PythonLockfileMetadata.new(
        InterpreterConstraints(), set()
    ).add_header_to_lockfile(b"", regenerate_command="regen", delimeter="#")
    rule_runner.write_files({"lock.txt": lock_content.decode()})

    lockfile = Lockfile(
        "lock.txt",
        file_path_description_of_origin="a test",
        resolve_name="a",
        req_strings=FrozenOrderedSet("ansicolors"),
    )
    with engine_error(InvalidLockfileError):
        create_pex_and_get_all_data(rule_runner, requirements=lockfile)

    lockfile_content = LockfileContent(
        FileContent("lock.txt", lock_content),
        resolve_name="a",
        req_strings=FrozenOrderedSet("ansicolors"),
    )
    with engine_error(InvalidLockfileError):
        create_pex_and_get_all_data(rule_runner, requirements=lockfile_content)
