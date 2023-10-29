# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
import re
import shutil
import textwrap
import zipfile
from pathlib import Path

import pytest
import requests
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pkg_resources import Requirement

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules import pex_test_utils
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadata
from pants.backend.python.util_rules.pex import (
    CompletePlatforms,
    Pex,
    PexDistributionInfo,
    PexPlatforms,
    PexProcess,
    PexRequest,
    PexRequirementsInfo,
    PexResolveInfo,
    VenvPex,
    VenvPexProcess,
    _build_pex_description,
    _BuildPexPythonSetup,
    _BuildPexRequirementsSetup,
    _determine_pex_python_and_platforms,
    _setup_pex_requirements,
)
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.backend.python.util_rules.pex_requirements import (
    EntireLockfile,
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
    PexRequirements,
    Resolve,
    ResolvePexConfig,
    ResolvePexConfigRequest,
)
from pants.backend.python.util_rules.pex_test_utils import (
    create_pex_and_get_all_data,
    create_pex_and_get_pex_info,
    parse_requirements,
)
from pants.core.goals.generate_lockfiles import GenerateLockfileResult
from pants.core.util_rules.lockfile_metadata import InvalidLockfileError
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    DigestContents,
    Directory,
    FileContent,
)
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.option.global_options import GlobalOptions
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import (
    PYTHON_BOOTSTRAP_ENV,
    MockGet,
    QueryRule,
    RuleRunner,
    engine_error,
    run_rule_with_mocks,
)
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_rmtree
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.pip_requirement import PipRequirement


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *pex_test_utils.rules(),
            *pex_rules(),
            QueryRule(GlobalOptions, []),
            QueryRule(ProcessResult, (Process,)),
            QueryRule(PexResolveInfo, (Pex,)),
            QueryRule(PexResolveInfo, (VenvPex,)),
        ],
    )


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
    req_strings = ["six==1.12.0", "jsonschema==2.6.0", "requests==2.23.0"]
    requirements = PexRequirements(req_strings)
    pex_info = create_pex_and_get_pex_info(rule_runner, requirements=requirements)
    # NB: We do not check for transitive dependencies, which PEX-INFO will include. We only check
    # that at least the dependencies we requested are included.
    assert set(parse_requirements(req_strings)).issubset(
        set(parse_requirements(pex_info["requirements"]))
    )


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


def test_lockfiles(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--python-invalid-lockfile-behavior=ignore"])
    rule_runner.write_files(
        {
            "pex_lock.json": textwrap.dedent(
                """\
                // Some Pants header
                // blah blah
                {
                  "allow_builds": true,
                  "allow_prereleases": false,
                  "allow_wheels": true,
                  "build_isolation": true,
                  "constraints": [],
                  "locked_resolves": [
                    {
                      "locked_requirements": [
                        {
                          "artifacts": [
                            {
                              "algorithm": "sha256",
                              "hash": "00d2dde5a675579325902536738dd27e4fac1fd68f773fe36c21044eb559e187",
                              "url": "https://files.pythonhosted.org/packages/53/18/a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/ansicolors-1.1.8-py2.py3-none-any.whl"
                            },
                            {
                              "algorithm": "sha256",
                              "hash": "99f94f5e3348a0bcd43c82e5fc4414013ccc19d70bd939ad71e0133ce9c372e0",
                              "url": "https://files.pythonhosted.org/packages/76/31/7faed52088732704523c259e24c26ce6f2f33fbeff2ff59274560c27628e/ansicolors-1.1.8.zip"
                            }
                          ],
                          "project_name": "ansicolors",
                          "requires_dists": [],
                          "requires_python": null,
                          "version": "1.1.8"
                        }
                      ],
                      "platform_tag": [
                        "cp39",
                        "cp39",
                        "macosx_11_0_arm64"
                      ]
                    }
                  ],
                  "pex_version": "2.1.70",
                  "prefer_older_binary": false,
                  "requirements": [
                    "ansicolors"
                  ],
                  "requires_python": [],
                  "resolver_version": "pip-2020-resolver",
                  "style": "universal",
                  "transitive": true,
                  "use_pep517": null
                }
                """
            ),
            "reqs_lock.txt": textwrap.dedent(
                """\
                ansicolors==1.1.8 \
                    --hash=sha256:00d2dde5a675579325902536738dd27e4fac1fd68f773fe36c21044eb559e187 \
                    --hash=sha256:99f94f5e3348a0bcd43c82e5fc4414013ccc19d70bd939ad71e0133ce9c372e0
                """
            ),
        }
    )

    def create_lock(path: str) -> None:
        lock = Lockfile(
            path,
            url_description_of_origin="foo",
            resolve_name="a",
        )
        create_pex_and_get_pex_info(
            rule_runner,
            requirements=EntireLockfile(lock, ("ansicolors",)),
            additional_pants_args=("--python-invalid-lockfile-behavior=ignore",),
        )

    create_lock("pex_lock.json")
    create_lock("reqs_lock.txt")


def test_entry_point(rule_runner: RuleRunner) -> None:
    entry_point = "pydoc"
    pex_info = create_pex_and_get_pex_info(rule_runner, main=EntryPoint(entry_point))
    assert pex_info["entry_point"] == entry_point


@pytest.mark.xfail(reason="#20103 this is intermittently flaky in CI", strict=False)
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


@pytest.mark.parametrize("use_pep440_rather_than_find_links", [True, False])
def test_local_requirements_and_path_mappings(
    use_pep440_rather_than_find_links: bool, tmp_path
) -> None:
    rule_runner = RuleRunner(
        rules=[
            *pex_test_utils.rules(),
            *pex_rules(),
            *lockfile.rules(),
            QueryRule(GenerateLockfileResult, [GeneratePythonLockfile]),
            QueryRule(PexResolveInfo, (Pex,)),
        ],
        bootstrap_args=[f"--named-caches-dir={tmp_path}"],
    )

    wheel_content = requests.get(
        "https://files.pythonhosted.org/packages/53/18/a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/ansicolors-1.1.8-py2.py3-none-any.whl"
    ).content

    with temporary_dir() as wheel_base_dir:
        dir1_path = Path(wheel_base_dir, "dir1")
        dir2_path = Path(wheel_base_dir, "dir2")
        dir1_path.mkdir()
        dir2_path.mkdir()

        wheel_path = dir1_path / "ansicolors-1.1.8-py2.py3-none-any.whl"
        wheel_req_str = (
            f"ansicolors @ file://{wheel_path}"
            if use_pep440_rather_than_find_links
            else "ansicolors"
        )
        wheel_path.write_bytes(wheel_content)

        def options(path_mappings_dir: Path) -> tuple[str, ...]:
            return (
                "--python-repos-indexes=[]",
                (
                    "--python-repos-find-links=[]"
                    if use_pep440_rather_than_find_links
                    else f"--python-repos-find-links={path_mappings_dir}"
                ),
                f"--python-repos-path-mappings=WHEEL_DIR|{path_mappings_dir}",
                f"--named-caches-dir={tmp_path}",
                # Use the vendored pip, so we don't have to set up a wheel for it in dir1_path.
                "--python-pip-version=20.3.4-patched",
            )

        rule_runner.set_options(options(dir1_path), env_inherit=PYTHON_BOOTSTRAP_ENV)
        lock_result = rule_runner.request(
            GenerateLockfileResult,
            [
                GeneratePythonLockfile(
                    requirements=FrozenOrderedSet([wheel_req_str]),
                    find_links=FrozenOrderedSet([]),
                    interpreter_constraints=InterpreterConstraints([">=3.7,<4"]),
                    resolve_name="test",
                    lockfile_dest="test.lock",
                    diff=False,
                )
            ],
        )
        lock_digest_contents = rule_runner.request(DigestContents, [lock_result.digest])
        assert len(lock_digest_contents) == 1
        lock_file_content = lock_digest_contents[0]
        assert b"${WHEEL_DIR}/ansicolors-1.1.8-py2.py3-none-any.whl" in lock_file_content.content
        assert b"files.pythonhosted.org" not in lock_file_content.content

        rule_runner.write_files({"test.lock": lock_file_content.content})
        lockfile_obj = EntireLockfile(
            Lockfile(url="test.lock", url_description_of_origin="test", resolve_name="test"),
            (wheel_req_str,),
        )

        # Wipe cache to ensure `--path-mappings` works.
        shutil.rmtree(tmp_path)
        shutil.rmtree(dir1_path)
        (dir2_path / "ansicolors-1.1.8-py2.py3-none-any.whl").write_bytes(wheel_content)
        pex_info = create_pex_and_get_all_data(
            rule_runner, requirements=lockfile_obj, additional_pants_args=options(dir2_path)
        ).info
        assert "ansicolors-1.1.8-py2.py3-none-any.whl" in pex_info["distributions"]

        # Confirm that pointing to a bad path fails.
        shutil.rmtree(tmp_path)
        shutil.rmtree(dir2_path)
        with engine_error():
            create_pex_and_get_all_data(
                rule_runner,
                requirements=lockfile_obj,
                additional_pants_args=options(Path(wheel_base_dir, "dir3")),
            )


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


def test_determine_pex_python_and_platforms() -> None:
    hardcoded_python = PythonExecutable("/hardcoded/python")
    discovered_python = PythonExecutable("/discovered/python")
    ics = InterpreterConstraints(["==3.7"])

    def assert_setup(
        *,
        input_python: PythonExecutable | None = None,
        platforms: PexPlatforms = PexPlatforms(),
        complete_platforms: CompletePlatforms = CompletePlatforms(),
        interpreter_constraints: InterpreterConstraints = InterpreterConstraints(),
        internal_only: bool = False,
        expected: _BuildPexPythonSetup,
    ) -> None:
        request = PexRequest(
            output_filename="foo.pex",
            internal_only=internal_only,
            python=input_python,
            platforms=platforms,
            complete_platforms=complete_platforms,
            interpreter_constraints=interpreter_constraints,
        )
        result = run_rule_with_mocks(
            _determine_pex_python_and_platforms,
            rule_args=[request],
            mock_gets=[
                MockGet(
                    output_type=PythonExecutable,
                    input_types=(InterpreterConstraints,),
                    mock=lambda _: discovered_python,
                )
            ],
        )
        assert result == expected

    assert_setup(expected=_BuildPexPythonSetup(None, []))
    assert_setup(
        interpreter_constraints=ics,
        expected=_BuildPexPythonSetup(None, ["--interpreter-constraint", "CPython==3.7"]),
    )
    assert_setup(
        internal_only=True,
        interpreter_constraints=ics,
        expected=_BuildPexPythonSetup(discovered_python, ["--python", discovered_python.path]),
    )
    assert_setup(
        internal_only=True,
        input_python=hardcoded_python,
        expected=_BuildPexPythonSetup(hardcoded_python, ["--python", hardcoded_python.path]),
    )
    assert_setup(
        platforms=PexPlatforms(["plat"]),
        interpreter_constraints=ics,
        expected=_BuildPexPythonSetup(None, ["--platform", "plat"]),
    )
    assert_setup(
        complete_platforms=CompletePlatforms(["plat"]),
        interpreter_constraints=ics,
        expected=_BuildPexPythonSetup(None, ["--complete-platform", "plat"]),
    )


def test_setup_pex_requirements() -> None:
    rule_runner = RuleRunner()

    reqs = ("req1", "req2")

    constraints_content = "constraint"
    constraints_digest = rule_runner.make_snapshot(
        {"__constraints.txt": constraints_content}
    ).digest

    lockfile_path = "foo.lock"
    lockfile_digest = rule_runner.make_snapshot_of_empty_files([lockfile_path]).digest
    lockfile_obj = Lockfile(lockfile_path, url_description_of_origin="foo", resolve_name="resolve")

    def create_loaded_lockfile(is_pex_lock: bool) -> LoadedLockfile:
        return LoadedLockfile(
            lockfile_digest,
            lockfile_path,
            metadata=None,
            requirement_estimate=2,
            is_pex_native=is_pex_lock,
            as_constraints_strings=None,
            original_lockfile=lockfile_obj,
        )

    def assert_setup(
        requirements: PexRequirements | EntireLockfile,
        expected: _BuildPexRequirementsSetup,
        *,
        is_pex_lock: bool = True,
        include_find_links: bool = False,
    ) -> None:
        request = PexRequest(
            output_filename="foo.pex",
            internal_only=True,
            requirements=requirements,
        )
        result = run_rule_with_mocks(
            _setup_pex_requirements,
            rule_args=[request, create_subsystem(PythonSetup)],
            mock_gets=[
                MockGet(
                    output_type=Lockfile,
                    input_types=(Resolve,),
                    mock=lambda _: lockfile_obj,
                ),
                MockGet(
                    output_type=LoadedLockfile,
                    input_types=(LoadedLockfileRequest,),
                    mock=lambda _: create_loaded_lockfile(is_pex_lock),
                ),
                MockGet(
                    output_type=PexRequirementsInfo,
                    input_types=(PexRequirements,),
                    mock=lambda _: PexRequirementsInfo(
                        tuple(str(x) for x in requirements.req_strings_or_addrs)
                        if isinstance(requirements, PexRequirements)
                        else tuple(),
                        ("imma/link",) if include_find_links else tuple(),
                    ),
                ),
                MockGet(
                    output_type=ResolvePexConfig,
                    input_types=(ResolvePexConfigRequest,),
                    mock=lambda _: ResolvePexConfig(
                        indexes=("custom-index",),
                        find_links=("custom-find-links",),
                        manylinux=None,
                        constraints_file=None,
                        only_binary=FrozenOrderedSet(),
                        no_binary=FrozenOrderedSet(),
                        path_mappings=(),
                    ),
                ),
                MockGet(
                    output_type=Digest,
                    input_types=(CreateDigest,),
                    mock=lambda _: constraints_digest,
                ),
            ],
        )
        assert result == expected

    pex_args = [
        "--no-pypi",
        "--index=custom-index",
        "--find-links=custom-find-links",
        "--no-manylinux",
    ]
    pip_args = [*pex_args, "--resolver-version", "pip-2020-resolver"]

    # Normal resolves.
    assert_setup(PexRequirements(reqs), _BuildPexRequirementsSetup([], [*reqs, *pip_args], 2))
    assert_setup(
        PexRequirements(reqs),
        _BuildPexRequirementsSetup([], [*reqs, *pip_args, "--find-links=imma/link"], 2),
        include_find_links=True,
    )
    assert_setup(
        PexRequirements(reqs, constraints_strings=["constraint"]),
        _BuildPexRequirementsSetup(
            [constraints_digest], [*reqs, *pip_args, "--constraints", "__constraints.txt"], 2
        ),
    )

    # Pex lockfile.
    assert_setup(
        EntireLockfile(lockfile_obj, complete_req_strings=reqs),
        _BuildPexRequirementsSetup([lockfile_digest], ["--lock", lockfile_path, *pex_args], 2),
    )

    # Non-Pex lockfile.
    assert_setup(
        EntireLockfile(lockfile_obj, complete_req_strings=reqs),
        _BuildPexRequirementsSetup(
            [lockfile_digest], ["--requirement", lockfile_path, "--no-transitive", *pip_args], 2
        ),
        is_pex_lock=False,
    )

    # Subset of Pex lockfile.
    assert_setup(
        PexRequirements(["req1"], from_superset=Resolve("resolve", False)),
        _BuildPexRequirementsSetup(
            [lockfile_digest], ["req1", "--lock", lockfile_path, *pex_args], 1
        ),
    )

    # Subset of repository Pex.
    repository_pex_digest = rule_runner.make_snapshot_of_empty_files(["foo.pex"]).digest
    assert_setup(
        PexRequirements(
            ["req1"], from_superset=Pex(digest=repository_pex_digest, name="foo.pex", python=None)
        ),
        _BuildPexRequirementsSetup(
            [repository_pex_digest], ["req1", "--pex-repository", "foo.pex"], 1
        ),
    )


def test_build_pex_description(rule_runner: RuleRunner) -> None:
    def assert_description(
        requirements: PexRequirements | EntireLockfile,
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
        req_strings = (
            requirements.req_strings_or_addrs if isinstance(requirements, PexRequirements) else []
        )
        assert (
            run_rule_with_mocks(
                _build_pex_description,
                rule_args=[request, req_strings, {}],
            )
            == expected
        )

    repo_pex = Pex(EMPTY_DIGEST, "repo.pex", None)

    assert_description(PexRequirements(), description="Custom!", expected="Custom!")
    assert_description(
        PexRequirements(from_superset=repo_pex), description="Custom!", expected="Custom!"
    )

    assert_description(PexRequirements(), expected="Building new.pex")
    assert_description(PexRequirements(from_superset=repo_pex), expected="Building new.pex")

    assert_description(
        PexRequirements(["req"]), expected="Building new.pex with 1 requirement: req"
    )
    assert_description(
        PexRequirements(["req"], from_superset=repo_pex),
        expected="Extracting 1 requirement to build new.pex from repo.pex: req",
    )

    assert_description(
        PexRequirements(["req1", "req2"]),
        expected="Building new.pex with 2 requirements: req1, req2",
    )
    assert_description(
        PexRequirements(["req1", "req2"], from_superset=repo_pex),
        expected="Extracting 2 requirements to build new.pex from repo.pex: req1, req2",
    )

    assert_description(
        EntireLockfile(
            Lockfile(
                url="lock.txt",
                url_description_of_origin="test",
                resolve_name="a",
            )
        ),
        expected="Building new.pex from lock.txt",
    )

    assert_description(
        EntireLockfile(
            Lockfile(
                url="lock.txt",
                url_description_of_origin="foo",
                resolve_name="a",
            )
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
        valid_for_interpreter_constraints=InterpreterConstraints(),
        requirements=set(),
        requirement_constraints=set(),
        only_binary=set(),
        no_binary=set(),
        manylinux=None,
    ).add_header_to_lockfile(b"", regenerate_command="regen", delimeter="#")
    rule_runner.write_files({"lock.txt": lock_content.decode()})

    _lockfile = Lockfile(
        "lock.txt",
        url_description_of_origin="a test",
        resolve_name="a",
    )
    with engine_error(InvalidLockfileError):
        create_pex_and_get_all_data(
            rule_runner, requirements=EntireLockfile(_lockfile, ("ansicolors",))
        )
