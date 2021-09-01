# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os.path
import re
import textwrap
import zipfile
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, Mapping, Tuple, cast
from unittest.mock import MagicMock

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pkg_resources import Requirement

from pants.backend.python.target_types import EntryPoint, MainSpecification
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import LockfileMetadata
from pants.backend.python.util_rules.pex import (
    Lockfile,
    LockfileContent,
    Pex,
    PexDistributionInfo,
    PexPlatforms,
    PexProcess,
    PexRequest,
    PexRequirements,
    PexResolveInfo,
    ResolvedDistributions,
    ToolCustomLockfile,
    ToolDefaultLockfile,
    VenvPex,
    VenvPexProcess,
    _build_pex_description,
    _validate_metadata,
)
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex_cli import PexPEX
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, Directory, FileContent
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.python.python_setup import InvalidLockfileBehavior
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.dirutil import safe_rmtree


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
    rule_runner = RuleRunner(
        rules=[
            *pex_rules(),
            QueryRule(Pex, (PexRequest,)),
            QueryRule(VenvPex, (PexRequest,)),
            QueryRule(ResolvedDistributions, (PexRequest,)),
            QueryRule(Process, (PexProcess,)),
            QueryRule(Process, (VenvPexProcess,)),
            QueryRule(ProcessResult, (Process,)),
            QueryRule(PexResolveInfo, (Pex,)),
            QueryRule(PexResolveInfo, (VenvPex,)),
            QueryRule(PexPEX, ()),
        ],
    )
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


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
                    Pex(digest=pex_pex.digest, name=pex_pex.exe, python=pex.python, pex_path=()),
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
    requirements: PexRequirements | Lockfile | LockfileContent = PexRequirements(),
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


@pytest.mark.parametrize("pex_type", [Pex, VenvPex])
def test_pex_working_directory(rule_runner: RuleRunner, pex_type: type[Pex | VenvPex]) -> None:
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

    pex_output = create_pex_and_get_all_data(
        rule_runner,
        pex_type=pex_type,
        main=EntryPoint("main"),
        sources=sources,
        interpreter_constraints=InterpreterConstraints(["CPython>=3.6"]),
    )

    pex = pex_output["pex"]
    pex_process_type = PexProcess if isinstance(pex, Pex) else VenvPexProcess

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
                    pex,
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
        if isinstance(pex, VenvPex):
            # Request once to ensure that the directory is seeded, and then start a new session so that
            # the second run happens as well.
            _ = rule_runner.request(ProcessResult, [process])
            rule_runner.new_session("re-run-for-venv-pex")
            rule_runner.set_options(
                ["--backend-packages=pants.backend.python"],
                env_inherit={"PATH", "PYENV_ROOT", "HOME"},
            )
            # Clear the cache.
            named_caches_dir = (
                rule_runner.options_bootstrapper.bootstrap_options.for_global_scope().named_caches_dir
            )
            venv_dir = os.path.join(named_caches_dir, "pex_root", pex.venv_rel_dir)
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


def test_requirement_constraints(rule_runner: RuleRunner) -> None:
    direct_deps = ["requests>=1.0.0,<=2.23.0"]

    def assert_direct_requirements(pex_info):
        assert set(Requirement.parse(r) for r in pex_info["requirements"]) == set(
            Requirement.parse(d) for d in direct_deps
        )

    # Unconstrained, we should always pick the top of the range (requests 2.23.0) since the top of
    # the range is a transitive closure over universal wheels.
    direct_pex_info = create_pex_and_get_pex_info(
        rule_runner, requirements=PexRequirements(direct_deps, apply_constraints=False)
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
    rule_runner.create_file("constraints.txt", "\n".join(constraints))
    constrained_pex_info = create_pex_and_get_pex_info(
        rule_runner,
        requirements=PexRequirements(direct_deps, apply_constraints=True),
        additional_pants_args=("--python-setup-requirement-constraints=constraints.txt",),
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
    constraints = [
        "requests==2.23.0",
        "certifi==2020.12.5",
        "chardet==3.0.4",
        "idna==2.10",
        "urllib3==1.25.11",
    ]
    rule_runner.create_file("constraints.txt", "\n".join(constraints))
    venv_pex = create_pex_and_get_all_data(
        rule_runner,
        pex_type=pex_type,
        requirements=PexRequirements(["requests==2.23.0"], apply_constraints=True),
        additional_pants_args=("--python-setup-requirement-constraints=constraints.txt",),
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


def test_build_pex_description() -> None:
    def assert_description(
        requirements: PexRequirements | Lockfile | LockfileContent,
        *,
        pex_path_length: int = 0,
        description: str | None = None,
        expected: str,
    ) -> None:
        request = PexRequest(
            output_filename="new.pex",
            internal_only=True,
            requirements=requirements,
            description=description,
            pex_path=(Pex(EMPTY_DIGEST, f"{i}.pex", None, ()) for i in range(0, pex_path_length)),
        )
        assert _build_pex_description(request) == expected

    resolved_dists = ResolvedDistributions(
        Pex(digest=EMPTY_DIGEST, name="repo.pex", python=None, pex_path=())
    )

    assert_description(PexRequirements(), description="Custom!", expected="Custom!")
    assert_description(
        PexRequirements(resolved_dists=resolved_dists), description="Custom!", expected="Custom!"
    )

    assert_description(PexRequirements(), expected="Building new.pex")
    assert_description(
        PexRequirements(resolved_dists=resolved_dists),
        pex_path_length=2,
        expected="Composing 2 requirements to build new.pex from repo.pex",
    )

    assert_description(
        PexRequirements(["req"]), expected="Building new.pex with 1 requirement: req"
    )
    assert_description(
        PexRequirements(["req"], resolved_dists=resolved_dists),
        expected="Extracting req from repo.pex",
    )

    assert_description(
        PexRequirements(["req1", "req2"]),
        expected="Building new.pex with 2 requirements: req1, req2",
    )
    assert_description(
        PexRequirements(["req1"], resolved_dists=resolved_dists),
        expected="Extracting req1 from repo.pex",
    )

    assert_description(
        LockfileContent(
            file_content=FileContent("lock.txt", b""),
            lockfile_hex_digest=None,
        ),
        expected="Resolving new.pex from lock.txt",
    )

    assert_description(
        Lockfile(
            file_path="lock.txt", file_path_description_of_origin="foo", lockfile_hex_digest=None
        ),
        expected="Resolving new.pex from lock.txt",
    )


DEFAULT = "DEFAULT"
FILE = "FILE"


def test_error_on_invalid_lockfile_with_path(rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError):
        _run_pex_for_lockfile_test(
            rule_runner,
            lockfile_type=FILE,
            behavior="error",
            invalid_reqs=True,
        )


def test_warn_on_invalid_lockfile_with_path(rule_runner: RuleRunner, caplog) -> None:
    _run_pex_for_lockfile_test(rule_runner, lockfile_type=FILE, behavior="warn", invalid_reqs=True)
    assert "but it is not compatible with your configuration" in caplog.text


def test_warn_on_requirements_mismatch(rule_runner: RuleRunner, caplog) -> None:
    _run_pex_for_lockfile_test(rule_runner, lockfile_type=FILE, behavior="warn", invalid_reqs=True)
    assert "You have set different requirements" in caplog.text
    assert "You have set interpreter constraints" not in caplog.text


def test_warn_on_interpreter_constraints_mismatch(rule_runner: RuleRunner, caplog) -> None:
    _run_pex_for_lockfile_test(
        rule_runner, lockfile_type=FILE, behavior="warn", invalid_constraints=True
    )
    assert "You have set different requirements" not in caplog.text
    assert "You have set interpreter constraints" in caplog.text


def test_warn_on_mismatched_requirements_and_interpreter_constraints(
    rule_runner: RuleRunner, caplog
) -> None:
    _run_pex_for_lockfile_test(
        rule_runner,
        lockfile_type=FILE,
        behavior="warn",
        invalid_reqs=True,
        invalid_constraints=True,
    )
    assert "You have set different requirements" in caplog.text
    assert "You have set interpreter constraints" in caplog.text


def test_ignore_on_invalid_lockfile_with_path(rule_runner: RuleRunner, caplog) -> None:
    _run_pex_for_lockfile_test(
        rule_runner, lockfile_type=FILE, behavior="ignore", invalid_reqs=True
    )
    assert not caplog.text.strip()


def test_no_warning_on_valid_lockfile_with_path(rule_runner: RuleRunner, caplog) -> None:
    _run_pex_for_lockfile_test(rule_runner, lockfile_type=FILE, behavior="warn")
    assert not caplog.text.strip()


def test_error_on_invalid_lockfile_with_content(rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError):
        _run_pex_for_lockfile_test(
            rule_runner, lockfile_type=DEFAULT, behavior="error", invalid_reqs=True
        )


def test_warn_on_invalid_lockfile_with_content(rule_runner: RuleRunner, caplog) -> None:
    _run_pex_for_lockfile_test(
        rule_runner, lockfile_type=DEFAULT, behavior="warn", invalid_reqs=True
    )
    assert "but it is not compatible with your configuration" in caplog.text


def test_no_warning_on_valid_lockfile_with_content(rule_runner: RuleRunner, caplog) -> None:
    _run_pex_for_lockfile_test(rule_runner, lockfile_type=DEFAULT, behavior="warn")
    assert not caplog.text.strip()


LOCKFILE_TYPES = (DEFAULT, FILE)
BOOLEANS = (True, False)


def _run_pex_for_lockfile_test(
    rule_runner,
    *,
    lockfile_type: str,
    behavior,
    invalid_reqs=False,
    invalid_constraints=False,
    uses_source_plugins=False,
    uses_project_ic=False,
) -> None:

    (
        actual_digest,
        expected_digest,
        actual_constraints,
        expected_constraints,
        options_scope_name,
    ) = _metadata_validation_values(
        invalid_reqs, invalid_constraints, uses_source_plugins, uses_project_ic
    )

    lockfile = f"""
# --- BEGIN PANTS LOCKFILE METADATA: DO NOT EDIT OR REMOVE ---
# {{
#   "requirements_invalidation_digest": "{actual_digest}",
#   "valid_for_interpreter_constraints": [
#     "{ actual_constraints }"
#   ]
# }}
# --- END PANTS LOCKFILE METADATA ---
ansicolors==1.1.8
"""

    requirements = _prepare_pex_requirements(
        rule_runner,
        lockfile_type,
        lockfile,
        expected_digest,
        options_scope_name,
        uses_source_plugins,
        uses_project_ic,
    )

    create_pex_and_get_all_data(
        rule_runner,
        interpreter_constraints=InterpreterConstraints([expected_constraints]),
        requirements=requirements,
        additional_pants_args=(
            "--python-setup-experimental-lockfile=lockfile.txt",
            f"--python-setup-invalid-lockfile-behavior={behavior}",
        ),
    )


@pytest.mark.parametrize(
    "lockfile_type,invalid_reqs,invalid_constraints,uses_source_plugins,uses_project_ic",
    [
        (lft, ir, ic, usp, upi)
        for lft in LOCKFILE_TYPES
        for ir in BOOLEANS
        for ic in BOOLEANS
        for usp in BOOLEANS
        for upi in BOOLEANS
        if (ir or ic)
    ],
)
def test_validate_metadata(
    rule_runner,
    lockfile_type: str,
    invalid_reqs,
    invalid_constraints,
    uses_source_plugins,
    uses_project_ic,
    caplog,
) -> None:
    class M:
        opening_default = "You are using the `<default>` lockfile provided by Pants"
        opening_file = "You are using the lockfile at"

        invalid_requirements = (
            "You have set different requirements than those used to generate the lockfile"
        )
        invalid_requirements_source_plugins = ".source_plugins`, and"

        invalid_interpreter_constraints = "You have set interpreter constraints"
        invalid_interpreter_constraints_tool_ics = (
            ".interpreter_constraints`, or by using a new custom lockfile."
        )
        invalid_interpreter_constraints_project_ics = (
            "determines its interpreter constraints based on your code's own constraints."
        )

        closing_lockfile_content = (
            "To generate a custom lockfile based on your current configuration"
        )
        closing_file = "To regenerate your lockfile based on your current configuration"

    (
        actual_digest,
        expected_digest,
        actual_constraints,
        expected_constraints,
        options_scope_name,
    ) = _metadata_validation_values(
        invalid_reqs, invalid_constraints, uses_source_plugins, uses_project_ic
    )

    metadata = LockfileMetadata(expected_digest, InterpreterConstraints([expected_constraints]))
    requirements = _prepare_pex_requirements(
        rule_runner,
        lockfile_type,
        "lockfile_data_goes_here",
        actual_digest,
        options_scope_name,
        uses_source_plugins,
        uses_project_ic,
    )

    request = MagicMock(
        options_scope_name=options_scope_name,
        interpreter_constraints=InterpreterConstraints([actual_constraints]),
    )
    python_setup = MagicMock(
        invalid_lockfile_behavior=InvalidLockfileBehavior.warn,
        interpreter_universe=["3.4", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10"],
    )

    _validate_metadata(metadata, request, requirements, python_setup)

    txt = caplog.text.strip()

    expected_opening = {
        DEFAULT: M.opening_default,
        FILE: M.opening_file,
    }[lockfile_type]

    assert expected_opening in txt

    if invalid_reqs:
        assert M.invalid_requirements in txt
        if uses_source_plugins:
            assert M.invalid_requirements_source_plugins in txt
        else:
            assert M.invalid_requirements_source_plugins not in txt
    else:
        assert M.invalid_requirements not in txt

    if invalid_constraints:
        assert M.invalid_interpreter_constraints in txt
        if uses_project_ic:
            assert M.invalid_interpreter_constraints_project_ics in txt
            assert M.invalid_interpreter_constraints_tool_ics not in txt
        else:
            assert M.invalid_interpreter_constraints_project_ics not in txt
            assert M.invalid_interpreter_constraints_tool_ics in txt

    else:
        assert M.invalid_interpreter_constraints not in txt

    if lockfile_type == FILE:
        assert M.closing_lockfile_content not in txt
        assert M.closing_file in txt


def _metadata_validation_values(
    invalid_reqs: bool, invalid_constraints: bool, uses_source_plugins: bool, uses_project_ic: bool
) -> tuple[str, str, str, str, str]:

    actual_digest = "900d"
    expected_digest = actual_digest
    if invalid_reqs:
        expected_digest = "baad"

    actual_constraints = "CPython>=3.6,<3.10"
    expected_constraints = actual_constraints
    if invalid_constraints:
        expected_constraints = "CPython>=3.9"

    options_scope_name: str
    if uses_source_plugins and uses_project_ic:
        options_scope_name = "pylint"
    elif uses_source_plugins:
        options_scope_name = "mypy"
    elif uses_project_ic:
        options_scope_name = "bandit"
    else:
        options_scope_name = "kevin"

    return (
        actual_digest,
        expected_digest,
        actual_constraints,
        expected_constraints,
        options_scope_name,
    )


def _prepare_pex_requirements(
    rule_runner: RuleRunner,
    lockfile_type: str,
    lockfile: str,
    expected_digest: str,
    options_scope_name: str,
    uses_source_plugins: bool,
    uses_project_interpreter_constraints: bool,
) -> Lockfile | LockfileContent:
    if lockfile_type == FILE:
        file_path = "lockfile.txt"
        rule_runner.write_files({file_path: lockfile})
        return ToolCustomLockfile(
            file_path=file_path,
            file_path_description_of_origin="iceland",
            lockfile_hex_digest=expected_digest,
            options_scope_name=options_scope_name,
            uses_source_plugins=uses_source_plugins,
            uses_project_interpreter_constraints=uses_project_interpreter_constraints,
        )
    elif lockfile_type == DEFAULT:
        content = FileContent("lockfile.txt", lockfile.encode("utf-8"))
        return ToolDefaultLockfile(
            file_content=content,
            lockfile_hex_digest=expected_digest,
            options_scope_name=options_scope_name,
            uses_source_plugins=uses_source_plugins,
            uses_project_interpreter_constraints=uses_project_interpreter_constraints,
        )
    else:
        raise Exception("incorrect lockfile_type value in test")
