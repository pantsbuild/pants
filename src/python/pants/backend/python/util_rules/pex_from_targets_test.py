# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.resources
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePath
from textwrap import dedent
from typing import Iterable, List, cast
from unittest.mock import Mock

import pytest

from pants.backend.plugin_development import pants_requirements
from pants.backend.plugin_development.pants_requirements import PantsRequirementsTargetGenerator
from pants.backend.python import target_types_rules
from pants.backend.python.goals import package_pex_binary
from pants.backend.python.subsystems import setuptools
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    EntryPoint,
    PexBinary,
    PexLayout,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestTarget,
)
from pants.backend.python.util_rules import pex_from_targets, pex_test_utils
from pants.backend.python.util_rules.pex import (
    OptionalPex,
    OptionalPexRequest,
    Pex,
    PexPlatforms,
    PexRequest,
    PexRequirementsInfo,
)
from pants.backend.python.util_rules.pex_from_targets import (
    ChosenPythonResolve,
    ChosenPythonResolveRequest,
    GlobalRequirementConstraints,
    PexFromTargetsRequest,
    _determine_requirements_for_pex_from_targets,
    _PexRequirementsRequest,
    _RepositoryPexRequest,
)
from pants.backend.python.util_rules.pex_requirements import (
    EntireLockfile,
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
    PexRequirements,
    Resolve,
)
from pants.backend.python.util_rules.pex_test_utils import get_all_data
from pants.build_graph.address import Address
from pants.core.goals.resolve_helpers import NoCompatibleResolveException
from pants.core.target_types import FileTarget, ResourceTarget
from pants.engine.addresses import Addresses
from pants.engine.fs import Snapshot
from pants.testutil.option_util import create_subsystem
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import MockGet, QueryRule, engine_error, run_rule_with_mocks
from pants.util.contextutil import pushd
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import softwrap


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *package_pex_binary.rules(),
            *pants_requirements.rules(),
            *pex_test_utils.rules(),
            *pex_from_targets.rules(),
            *target_types_rules.rules(),
            QueryRule(PexRequest, (PexFromTargetsRequest,)),
            QueryRule(PexRequirementsInfo, (PexRequirements,)),
            QueryRule(GlobalRequirementConstraints, ()),
            QueryRule(ChosenPythonResolve, [ChosenPythonResolveRequest]),
            *setuptools.rules(),
        ],
        target_types=[
            PantsRequirementsTargetGenerator,
            PexBinary,
            PythonSourcesGeneratorTarget,
            PythonRequirementTarget,
            PythonSourceTarget,
            PythonTestTarget,
            FileTarget,
            ResourceTarget,
        ],
    )


@pytest.mark.skip(reason="TODO(#15824)")
@pytest.mark.no_error_if_skipped
def test_choose_compatible_resolve(rule_runner: PythonRuleRunner) -> None:
    def create_target_files(
        directory: str, *, req_resolve: str, source_resolve: str, test_resolve: str
    ) -> dict[str, str]:
        return {
            f"{directory}/BUILD": dedent(
                f"""\
              python_source(name="dep", source="dep.py", resolve="{source_resolve}")
              python_requirement(
                  name="req", requirements=[], resolve="{req_resolve}"
              )
              python_test(
                  name="test",
                  source="tests.py",
                  dependencies=[":dep", ":req"],
                  resolve="{test_resolve}",
              )
              """
            ),
            f"{directory}/tests.py": "",
            f"{directory}/dep.py": "",
        }

    rule_runner.set_options(
        ["--python-resolves={'a': '', 'b': ''}", "--python-enable-resolves"], env_inherit={"PATH"}
    )
    rule_runner.write_files(
        {
            # Note that each of these BUILD files are entirely self-contained.
            **create_target_files("valid", req_resolve="a", source_resolve="a", test_resolve="a"),
            **create_target_files(
                "invalid",
                req_resolve="a",
                source_resolve="a",
                test_resolve="b",
            ),
        }
    )

    def choose_resolve(addresses: list[Address]) -> str:
        return rule_runner.request(
            ChosenPythonResolve, [ChosenPythonResolveRequest(Addresses(addresses))]
        ).name

    assert choose_resolve([Address("valid", target_name="test")]) == "a"
    assert choose_resolve([Address("valid", target_name="dep")]) == "a"
    assert choose_resolve([Address("valid", target_name="req")]) == "a"

    with engine_error(NoCompatibleResolveException, contains="its dependencies are not compatible"):
        choose_resolve([Address("invalid", target_name="test")])
    with engine_error(NoCompatibleResolveException, contains="its dependencies are not compatible"):
        choose_resolve([Address("invalid", target_name="dep")])

    with engine_error(
        NoCompatibleResolveException, contains="input targets did not have a resolve"
    ):
        choose_resolve(
            [Address("invalid", target_name="req"), Address("invalid", target_name="dep")]
        )


def test_determine_requirements_for_pex_from_targets() -> None:
    class RequirementMode(Enum):
        PEX_LOCKFILE = 1
        NON_PEX_LOCKFILE = 2
        # Note that enable_resolves is mutually exclusive with requirement_constraints.
        CONSTRAINTS_RESOLVE_ALL = 3
        CONSTRAINTS_NO_RESOLVE_ALL = 4
        NO_LOCKS = 5

    req_strings = ["req1", "req2"]
    global_requirement_constraints = ["constraint1", "constraint2"]

    resolve__pex = Resolve("pex", False)
    loaded_lockfile__pex = Mock(is_pex_native=True, as_constraints_strings=None)
    chosen_resolve__pex = Mock(lockfile=Mock())
    chosen_resolve__pex.name = "pex"  # name has special meaning in Mock(), so must set it here.
    resolve__not_pex = Resolve("not_pex", False)
    loaded_lockfile__not_pex = Mock(is_pex_native=False, as_constraints_strings=req_strings)
    chosen_resolve__not_pex = Mock(lockfile=Mock())
    chosen_resolve__not_pex.name = "not_pex"  # ditto.

    repository_pex_request__lockfile = Mock()
    repository_pex_request__constraints = Mock()

    repository_pex__lockfile = Mock()
    repository_pex__constraints = Mock()

    def assert_setup(
        _mode: RequirementMode,
        *,
        _internal_only: bool,
        _platforms: bool,
        include_requirements: bool = True,
        run_against_entire_lockfile: bool = False,
        expected_reqs: PexRequirements = PexRequirements(),
        expected_pexes: Iterable[Pex] = (),
    ) -> None:
        lockfile_used = _mode in (RequirementMode.PEX_LOCKFILE, RequirementMode.NON_PEX_LOCKFILE)
        requirement_constraints_used = _mode in (
            RequirementMode.CONSTRAINTS_RESOLVE_ALL,
            RequirementMode.CONSTRAINTS_NO_RESOLVE_ALL,
        )

        python_setup = create_subsystem(
            PythonSetup,
            enable_resolves=lockfile_used,
            run_against_entire_lockfile=run_against_entire_lockfile,
            resolve_all_constraints=_mode != RequirementMode.CONSTRAINTS_NO_RESOLVE_ALL,
            requirement_constraints="foo.constraints" if requirement_constraints_used else None,
        )
        pex_from_targets_request = PexFromTargetsRequest(
            Addresses(),
            output_filename="foo",
            include_requirements=include_requirements,
            platforms=PexPlatforms(["foo"] if _platforms else []),
            internal_only=_internal_only,
        )
        resolved_pex_requirements = PexRequirements(
            req_strings,
            constraints_strings=(
                global_requirement_constraints if requirement_constraints_used else ()
            ),
        )

        # NB: We recreate that platforms should turn off first creating a repository.pex.
        if lockfile_used and not _platforms:
            mock_repository_pex_request = OptionalPexRequest(
                maybe_pex_request=repository_pex_request__lockfile
            )
            mock_repository_pex = OptionalPex(maybe_pex=repository_pex__lockfile)
        elif _mode == RequirementMode.CONSTRAINTS_RESOLVE_ALL and not _platforms:
            mock_repository_pex_request = OptionalPexRequest(
                maybe_pex_request=repository_pex_request__constraints
            )
            mock_repository_pex = OptionalPex(maybe_pex=repository_pex__constraints)
        else:
            mock_repository_pex_request = OptionalPexRequest(maybe_pex_request=None)
            mock_repository_pex = OptionalPex(maybe_pex=None)

        reqs, pexes = run_rule_with_mocks(
            _determine_requirements_for_pex_from_targets,
            rule_args=[pex_from_targets_request, python_setup],
            mock_gets=[
                MockGet(
                    output_type=PexRequirements,
                    input_types=(_PexRequirementsRequest,),
                    mock=lambda _: resolved_pex_requirements,
                ),
                MockGet(
                    output_type=ChosenPythonResolve,
                    input_types=(ChosenPythonResolveRequest,),
                    mock=lambda _: (
                        chosen_resolve__pex
                        if _mode == RequirementMode.PEX_LOCKFILE
                        else chosen_resolve__not_pex
                    ),
                ),
                MockGet(
                    output_type=Lockfile,
                    input_types=(Resolve,),
                    mock=lambda _: (
                        resolve__pex if _mode == RequirementMode.PEX_LOCKFILE else resolve__not_pex
                    ),
                ),
                MockGet(
                    output_type=LoadedLockfile,
                    input_types=(LoadedLockfileRequest,),
                    mock=lambda _: (
                        loaded_lockfile__pex
                        if _mode == RequirementMode.PEX_LOCKFILE
                        else loaded_lockfile__not_pex
                    ),
                ),
                MockGet(
                    output_type=OptionalPexRequest,
                    input_types=(_RepositoryPexRequest,),
                    mock=lambda _: mock_repository_pex_request,
                ),
                MockGet(
                    output_type=OptionalPex,
                    input_types=(OptionalPexRequest,),
                    mock=lambda _: mock_repository_pex,
                ),
            ],
        )
        assert expected_reqs == reqs
        assert expected_pexes == pexes

    # If include_requirements is False, no matter what, early return.
    for mode in RequirementMode:
        assert_setup(
            mode,
            include_requirements=False,
            _internal_only=False,
            _platforms=False,
            # Nothing is expected
        )

    # Pex lockfiles: usually, return PexRequirements with from_superset as the resolve.
    #   Except for when run_against_entire_lockfile is set and it's an internal_only Pex, then
    #   return PexRequest.
    for internal_only in (True, False):
        assert_setup(
            RequirementMode.PEX_LOCKFILE,
            _internal_only=internal_only,
            _platforms=False,
            expected_reqs=PexRequirements(req_strings, from_superset=resolve__pex),
        )

    assert_setup(
        RequirementMode.PEX_LOCKFILE,
        _internal_only=False,
        _platforms=True,
        expected_reqs=PexRequirements(req_strings, from_superset=resolve__pex),
    )
    for platforms in (True, False):
        assert_setup(
            RequirementMode.PEX_LOCKFILE,
            _internal_only=False,
            run_against_entire_lockfile=True,
            _platforms=platforms,
            expected_reqs=PexRequirements(req_strings, from_superset=resolve__pex),
        )
    assert_setup(
        RequirementMode.PEX_LOCKFILE,
        _internal_only=True,
        run_against_entire_lockfile=True,
        _platforms=False,
        expected_reqs=repository_pex_request__lockfile.requirements,
        expected_pexes=[repository_pex__lockfile],
    )

    # Non-Pex lockfiles: except for when run_against_entire_lockfile is applicable, return
    # PexRequirements with from_superset as the lockfile repository Pex and constraint_strings as
    # the lockfile's requirements.
    for internal_only in (False, True):
        assert_setup(
            RequirementMode.NON_PEX_LOCKFILE,
            _internal_only=internal_only,
            _platforms=False,
            expected_reqs=PexRequirements(
                req_strings, constraints_strings=req_strings, from_superset=repository_pex__lockfile
            ),
        )
    assert_setup(
        RequirementMode.NON_PEX_LOCKFILE,
        _internal_only=False,
        _platforms=True,
        expected_reqs=PexRequirements(
            req_strings, constraints_strings=req_strings, from_superset=None
        ),
    )
    assert_setup(
        RequirementMode.NON_PEX_LOCKFILE,
        _internal_only=False,
        run_against_entire_lockfile=True,
        _platforms=False,
        expected_reqs=PexRequirements(
            req_strings, constraints_strings=req_strings, from_superset=repository_pex__lockfile
        ),
    )
    assert_setup(
        RequirementMode.NON_PEX_LOCKFILE,
        _internal_only=False,
        run_against_entire_lockfile=True,
        _platforms=True,
        expected_reqs=PexRequirements(
            req_strings, constraints_strings=req_strings, from_superset=None
        ),
    )
    assert_setup(
        RequirementMode.NON_PEX_LOCKFILE,
        _internal_only=True,
        run_against_entire_lockfile=True,
        _platforms=False,
        expected_reqs=repository_pex_request__lockfile.requirements,
        expected_pexes=[repository_pex__lockfile],
    )

    # Constraints file with resolve_all_constraints: except for when run_against_entire_lockfile
    #   is applicable, return PexRequirements with from_superset as the constraints repository Pex
    #   and constraint_strings as the global constraints.
    for internal_only in (False, True):
        assert_setup(
            RequirementMode.CONSTRAINTS_RESOLVE_ALL,
            _internal_only=internal_only,
            _platforms=False,
            expected_reqs=PexRequirements(
                req_strings,
                constraints_strings=global_requirement_constraints,
                from_superset=repository_pex__constraints,
            ),
        )
    assert_setup(
        RequirementMode.CONSTRAINTS_RESOLVE_ALL,
        _internal_only=False,
        _platforms=True,
        expected_reqs=PexRequirements(
            req_strings, constraints_strings=global_requirement_constraints, from_superset=None
        ),
    )
    assert_setup(
        RequirementMode.CONSTRAINTS_RESOLVE_ALL,
        _internal_only=False,
        run_against_entire_lockfile=True,
        _platforms=False,
        expected_reqs=PexRequirements(
            req_strings,
            constraints_strings=global_requirement_constraints,
            from_superset=repository_pex__constraints,
        ),
    )
    assert_setup(
        RequirementMode.CONSTRAINTS_RESOLVE_ALL,
        _internal_only=False,
        run_against_entire_lockfile=True,
        _platforms=True,
        expected_reqs=PexRequirements(
            req_strings, constraints_strings=global_requirement_constraints, from_superset=None
        ),
    )
    assert_setup(
        RequirementMode.CONSTRAINTS_RESOLVE_ALL,
        _internal_only=True,
        run_against_entire_lockfile=True,
        _platforms=False,
        expected_reqs=repository_pex_request__constraints.requirements,
        expected_pexes=[repository_pex__constraints],
    )

    # Constraints file without resolve_all_constraints: always PexRequirements with
    #   constraint_strings as the global constraints.
    for internal_only in (True, False):
        assert_setup(
            RequirementMode.CONSTRAINTS_NO_RESOLVE_ALL,
            _internal_only=internal_only,
            _platforms=platforms,
            expected_reqs=PexRequirements(
                req_strings, constraints_strings=global_requirement_constraints
            ),
        )
    for platforms in (True, False):
        assert_setup(
            RequirementMode.CONSTRAINTS_NO_RESOLVE_ALL,
            _internal_only=False,
            _platforms=platforms,
            expected_reqs=PexRequirements(
                req_strings, constraints_strings=global_requirement_constraints
            ),
        )

    # No constraints and lockfiles: return PexRequirements without modification.
    for internal_only in (True, False):
        assert_setup(
            RequirementMode.NO_LOCKS,
            _internal_only=internal_only,
            _platforms=False,
            expected_reqs=PexRequirements(req_strings),
        )
    assert_setup(
        RequirementMode.NO_LOCKS,
        _internal_only=False,
        _platforms=True,
        expected_reqs=PexRequirements(req_strings),
    )


@dataclass(frozen=True)
class Project:
    name: str
    version: str


build_deps = ["setuptools==54.1.2", "wheel==0.36.2"]


setuptools_poetry_lockfile = r"""
# This lockfile was autogenerated by Pants. To regenerate, run:
#
#    ./pants generate-lockfiles --resolve=setuptools
#
# --- BEGIN PANTS LOCKFILE METADATA: DO NOT EDIT OR REMOVE ---
# {
#   "version": 2,
#   "valid_for_interpreter_constraints": [
#     "CPython>=3.7"
#   ],
#   "generated_with_requirements": [
#     "setuptools==54.1.2"
#   ]
# }
# --- END PANTS LOCKFILE METADATA ---

setuptools==54.1.2; python_version >= "3.6" \
    --hash=sha256:dd20743f36b93cbb8724f4d2ccd970dce8b6e6e823a13aa7e5751bb4e674c20b \
    --hash=sha256:ebd0148faf627b569c8d2a1b20f5d3b09c873f12739d71c7ee88f037d5be82ff
"""


def create_project_dir(workdir: Path, project: Project) -> PurePath:
    project_dir = workdir / "projects" / project.name
    project_dir.mkdir(parents=True)

    (project_dir / "pyproject.toml").write_text(
        dedent(
            f"""\
            [build-system]
            requires = {build_deps}
            build-backend = "setuptools.build_meta"
            """
        )
    )
    (project_dir / "setup.cfg").write_text(
        dedent(
            f"""\
                [metadata]
                name = {project.name}
                version = {project.version}
                """
        )
    )
    return project_dir


def create_dists(workdir: Path, project: Project, *projects: Project) -> PurePath:
    project_dirs = [create_project_dir(workdir, proj) for proj in (project, *projects)]

    pex = workdir / "pex"
    subprocess.run(
        args=[
            sys.executable,
            "-m",
            "pex",
            *project_dirs,
            *build_deps,
            "--include-tools",
            "-o",
            pex,
        ],
        check=True,
    )

    find_links = workdir / "find-links"
    subprocess.run(
        args=[
            sys.executable,
            "-m",
            "pex.tools",
            pex,
            "repository",
            "extract",
            "--find-links",
            find_links,
        ],
        check=True,
    )
    return find_links


def requirements(rule_runner: PythonRuleRunner, pex: Pex) -> list[str]:
    return cast(List[str], get_all_data(rule_runner, pex).info["requirements"])


def test_constraints_validation(tmp_path: Path, rule_runner: PythonRuleRunner) -> None:
    sdists = tmp_path / "sdists"
    sdists.mkdir()
    find_links = create_dists(
        sdists,
        Project("Foo-Bar", "1.0.0"),
        Project("Bar", "5.5.5"),
        Project("baz", "2.2.2"),
        Project("QUX", "3.4.5"),
    )

    # Turn the project dir into a git repo, so it can be cloned.
    gitdir = tmp_path / "git"
    gitdir.mkdir()
    foorl_dir = create_project_dir(gitdir, Project("foorl", "9.8.7"))
    with pushd(str(foorl_dir)):
        subprocess.check_call(["git", "init"])
        subprocess.check_call(["git", "config", "user.name", "dummy"])
        subprocess.check_call(["git", "config", "user.email", "dummy@dummy.com"])
        subprocess.check_call(["git", "add", "--all"])
        subprocess.check_call(["git", "commit", "-m", "initial commit"])
        subprocess.check_call(["git", "branch", "9.8.7"])

    # This string won't parse as a Requirement if it doesn't contain a netloc,
    # so we explicitly mention localhost.
    url_req = f"foorl@ git+file://localhost{foorl_dir.as_posix()}@9.8.7"

    rule_runner.write_files(
        {
            "util.py": "",
            "app.py": "",
            "BUILD": dedent(
                f"""
                python_requirement(name="foo", requirements=["foo-bar>=0.1.2"])
                python_requirement(name="bar", requirements=["bar==5.5.5"])
                python_requirement(name="baz", requirements=["baz"])
                python_requirement(name="foorl", requirements=["{url_req}"])
                python_sources(name="util", sources=["util.py"], dependencies=[":foo", ":bar"])
                python_sources(name="app", sources=["app.py"], dependencies=[":util", ":baz", ":foorl"])
                """
            ),
            "constraints1.txt": dedent(
                """
                # Comment.
                --find-links=https://duckduckgo.com
                Foo._-BAR==1.0.0  # Inline comment.
                bar==5.5.5
                baz==2.2.2
                qux==3.4.5
                # Note that pip does not allow URL requirements in constraints files,
                # so there is no mention of foorl here.
                """
            ),
        }
    )

    # Create and parse the constraints file.
    constraints1_filename = "constraints1.txt"
    rule_runner.set_options(
        [f"--python-requirement-constraints={constraints1_filename}"], env_inherit={"PATH"}
    )
    constraints1_strings = [str(c) for c in rule_runner.request(GlobalRequirementConstraints, [])]

    def get_pex_request(
        constraints_file: str | None,
        resolve_all_constraints: bool | None,
        *,
        _additional_args: Iterable[str] = (),
        _additional_lockfile_args: Iterable[str] = (),
    ) -> PexRequest:
        args = ["--backend-packages=pants.backend.python"]
        request = PexFromTargetsRequest(
            [Address("", target_name="app")],
            output_filename="demo.pex",
            internal_only=True,
            additional_args=_additional_args,
            additional_lockfile_args=_additional_lockfile_args,
        )
        if resolve_all_constraints is not None:
            args.append(f"--python-resolve-all-constraints={resolve_all_constraints!r}")
        if constraints_file:
            args.append(f"--python-requirement-constraints={constraints_file}")
        args.append("--python-repos-indexes=[]")
        args.append(f"--python-repos-repos={find_links}")
        rule_runner.set_options(args, env_inherit={"PATH"})
        pex_request = rule_runner.request(PexRequest, [request])
        assert OrderedSet(_additional_args).issubset(OrderedSet(pex_request.additional_args))
        return pex_request

    additional_args = ["--strip-pex-env"]
    additional_lockfile_args = ["--no-strip-pex-env"]

    pex_req1 = get_pex_request(constraints1_filename, resolve_all_constraints=False)
    assert isinstance(pex_req1.requirements, PexRequirements)
    assert pex_req1.requirements.constraints_strings == FrozenOrderedSet(constraints1_strings)
    req_strings_obj1 = rule_runner.request(PexRequirementsInfo, (pex_req1.requirements,))
    assert req_strings_obj1.req_strings == ("bar==5.5.5", "baz", "foo-bar>=0.1.2", url_req)

    pex_req2 = get_pex_request(
        constraints1_filename,
        resolve_all_constraints=True,
        _additional_args=additional_args,
        _additional_lockfile_args=additional_lockfile_args,
    )
    pex_req2_reqs = pex_req2.requirements
    assert isinstance(pex_req2_reqs, PexRequirements)
    req_strings_obj2 = rule_runner.request(PexRequirementsInfo, (pex_req2_reqs,))
    assert req_strings_obj2.req_strings == ("bar==5.5.5", "baz", "foo-bar>=0.1.2", url_req)
    assert isinstance(pex_req2_reqs.from_superset, Pex)
    repository_pex = pex_req2_reqs.from_superset
    assert not get_all_data(rule_runner, repository_pex).info["strip_pex_env"]
    assert ["Foo._-BAR==1.0.0", "bar==5.5.5", "baz==2.2.2", "foorl", "qux==3.4.5"] == requirements(
        rule_runner, repository_pex
    )

    with engine_error(
        ValueError,
        contains=softwrap(
            """
            `[python].resolve_all_constraints` is enabled, so
            `[python].requirement_constraints` must also be set.
            """
        ),
    ):
        get_pex_request(None, resolve_all_constraints=True)

    # Shouldn't error, as we don't explicitly set --resolve-all-constraints.
    get_pex_request(None, resolve_all_constraints=None)


def test_pants_requirement(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "app.py": "",
            "BUILD": dedent(
                """
                pants_requirements(name="pants")
                python_source(name="app", source="app.py", dependencies=[":pants"])
                """
            ),
        }
    )
    args = [
        "--backend-packages=pants.backend.python",
        "--backend-packages=pants.backend.plugin_development",
        "--python-repos-indexes=[]",
    ]
    request = PexFromTargetsRequest(
        [Address("", target_name="app")],
        output_filename="demo.pex",
        internal_only=False,
    )
    rule_runner.set_options(args, env_inherit={"PATH"})
    pex_req = rule_runner.request(PexRequest, [request])
    pex_reqs_info = rule_runner.request(PexRequirementsInfo, [pex_req.requirements])
    assert pex_reqs_info.find_links == ("https://wheels.pantsbuild.org/simple",)


@pytest.mark.parametrize("include_requirements", [False, True])
def test_exclude_requirements(
    include_requirements: bool, tmp_path: Path, rule_runner: PythonRuleRunner
) -> None:
    sdists = tmp_path / "sdists"
    sdists.mkdir()
    find_links = create_dists(sdists, Project("baz", "2.2.2"))

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                python_requirement(name="baz", requirements=["foo==1.2.3"])
                python_sources(name="app", sources=["app.py"], dependencies=[":baz"])
                """
            ),
            "constraints.txt": dedent("foo==1.2.3"),
            "app.py": "",
        }
    )

    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python",
            "--python-repos-indexes=[]",
            f"--python-repos-repos={find_links}",
        ],
        env_inherit={"PATH"},
    )

    request = PexFromTargetsRequest(
        [Address("", target_name="app")],
        output_filename="demo.pex",
        internal_only=True,
        include_requirements=include_requirements,
    )
    pex_request = rule_runner.request(PexRequest, [request])
    assert isinstance(pex_request.requirements, PexRequirements)
    assert len(pex_request.requirements.req_strings_or_addrs) == (1 if include_requirements else 0)


@pytest.mark.parametrize("include_sources", [False, True])
def test_exclude_sources(include_sources: bool, rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                python_sources(name="app", sources=["app.py"])
                """
            ),
            "app.py": "",
        }
    )

    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python",
            "--python-repos-indexes=[]",
        ],
        env_inherit={"PATH"},
    )

    request = PexFromTargetsRequest(
        [Address("", target_name="app")],
        output_filename="demo.pex",
        internal_only=True,
        include_source_files=include_sources,
    )
    pex_request = rule_runner.request(PexRequest, [request])
    snapshot = rule_runner.request(Snapshot, [pex_request.sources])
    assert len(snapshot.files) == (1 if include_sources else 0)


def test_include_sources_without_transitive_package_sources(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/app/BUILD": dedent(
                """
                python_sources(
                    name="app",
                    sources=["app.py"],
                    dependencies=["//src/dep:pkg"],
                )
                """
            ),
            "src/app/app.py": "",
            "src/dep/BUILD": dedent(
                # This test requires a package that has a standard dependencies field.
                # 'pex_binary' has a dependencies field; 'archive' does not.
                """
                pex_binary(name="pkg", dependencies=[":dep"])
                python_sources(name="dep", sources=["dep.py"])
                """
            ),
            "src/dep/dep.py": "",
        }
    )

    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python",
            "--python-repos-indexes=[]",
        ],
        env_inherit={"PATH"},
    )

    request = PexFromTargetsRequest(
        [Address("src/app", target_name="app")],
        output_filename="demo.pex",
        internal_only=True,
        include_source_files=True,
    )
    pex_request = rule_runner.request(PexRequest, [request])
    snapshot = rule_runner.request(Snapshot, [pex_request.sources])

    # the packaged transitive dep is excluded
    assert snapshot.files == ("app/app.py",)


@pytest.mark.parametrize("enable_resolves", [False, True])
def test_cross_platform_pex_disables_subsetting(
    rule_runner: PythonRuleRunner, enable_resolves: bool
) -> None:
    # See https://github.com/pantsbuild/pants/issues/12222.
    lockfile = "3rdparty/python/default.lock"
    constraints = ["foo==1.0", "bar==1.0"]
    rule_runner.write_files(
        {
            lockfile: "\n".join(constraints),
            "a.py": "",
            "BUILD": dedent(
                """
                python_requirement(name="foo",requirements=["foo"])
                python_requirement(name="bar",requirements=["bar"])
                python_sources(name="lib",dependencies=[":foo"])
                """
            ),
        }
    )

    if enable_resolves:
        options = [
            "--python-enable-resolves",
            # NB: Because this is a synthetic lockfile without a header.
            "--python-invalid-lockfile-behavior=ignore",
        ]
    else:
        options = [
            f"--python-requirement-constraints={lockfile}",
            "--python-resolve-all-constraints",
        ]
    rule_runner.set_options(options, env_inherit={"PATH"})

    request = PexFromTargetsRequest(
        [Address("", target_name="lib")],
        output_filename="demo.pex",
        internal_only=False,
        platforms=PexPlatforms(["some-platform-x86_64"]),
    )
    result = rule_runner.request(PexRequest, [request])

    assert result.requirements == PexRequirements(
        request.addresses,
        constraints_strings=constraints,
        description_of_origin="//:lib",
    )


class ResolveMode(Enum):
    resolve_all_constraints = "resolve_all_constraints"
    poetry_or_manual = "poetry_or_manual"
    pex = "pex"


@pytest.mark.parametrize(
    "mode,internal_only,run_against_entire_lockfile",
    [(m, io, rael) for m in ResolveMode for io in [True, False] for rael in [True, False]],
)
def test_lockfile_requirements_selection(
    rule_runner: PythonRuleRunner,
    mode: ResolveMode,
    internal_only: bool,
    run_against_entire_lockfile: bool,
) -> None:
    mode_files: dict[str, str | bytes] = {
        "a.py": "",
        "BUILD": dedent(
            """
                python_sources(name="lib", dependencies=[":setuptools"])
                python_requirement(name="setuptools", requirements=["setuptools"])
                """
        ),
    }
    if mode == ResolveMode.resolve_all_constraints:
        mode_files.update({"constraints.txt": "setuptools==54.1.2"})
    elif mode == ResolveMode.poetry_or_manual:
        mode_files.update({"3rdparty/python/default.lock": setuptools_poetry_lockfile})
    else:
        assert mode == ResolveMode.pex
        lock_content = importlib.resources.read_binary(
            "pants.backend.python.subsystems", "setuptools.lock"
        )
        mode_files.update({"3rdparty/python/default.lock": lock_content})

    rule_runner.write_files(mode_files)

    if mode == ResolveMode.resolve_all_constraints:
        options = [
            "--python-requirement-constraints=constraints.txt",
        ]
    else:
        # NB: It doesn't matter what the lockfile generator is set to: only what is actually on disk.
        options = [
            "--python-enable-resolves",
            "--python-default-resolve=myresolve",
            "--python-resolves={'myresolve':'3rdparty/python/default.lock'}",
        ]

    if run_against_entire_lockfile:
        options.append("--python-run-against-entire-lockfile")

    request = PexFromTargetsRequest(
        [Address("", target_name="lib")],
        output_filename="demo.pex",
        internal_only=internal_only,
        main=EntryPoint("a"),
    )
    rule_runner.set_options(options, env_inherit={"PATH"})
    result = rule_runner.request(PexRequest, [request])
    assert result.layout == (PexLayout.PACKED if internal_only else PexLayout.ZIPAPP)
    assert result.main == EntryPoint("a")

    if run_against_entire_lockfile and internal_only:
        # With `run_against_entire_lockfile`, all internal requests result in the full set
        # of requirements, but that is encoded slightly differently per mode.
        if mode == ResolveMode.resolve_all_constraints:
            # NB: The use of the legacy constraints file with `resolve_all_constraints` requires parsing
            # and manipulation of the constraints, and needs to include transitive deps (unlike other
            # lockfile requests). So it is emitted as `PexRequirements` rather than EntireLockfile.
            assert isinstance(result.requirements, PexRequirements)
            assert not result.requirements.from_superset
        else:
            assert mode in (ResolveMode.poetry_or_manual, ResolveMode.pex)
            assert isinstance(result.requirements, EntireLockfile)
    else:
        assert isinstance(result.requirements, PexRequirements)
        if mode in (ResolveMode.resolve_all_constraints, ResolveMode.poetry_or_manual):
            assert isinstance(result.requirements.from_superset, Pex)
            assert not get_all_data(rule_runner, result.requirements.from_superset).is_zipapp
        else:
            assert mode == ResolveMode.pex
            assert isinstance(result.requirements.from_superset, Resolve)
            assert result.requirements.from_superset.name == "myresolve"


def test_warn_about_files_targets(rule_runner: PythonRuleRunner, caplog) -> None:
    rule_runner.write_files(
        {
            "app.py": "",
            "file.txt": "",
            "resource.txt": "",
            "BUILD": dedent(
                """
                file(name="file_target", source="file.txt")
                resource(name="resource_target", source="resource.txt")
                python_sources(name="app", dependencies=[":file_target", ":resource_target"])
                """
            ),
        }
    )

    rule_runner.request(
        PexRequest,
        [
            PexFromTargetsRequest(
                [Address("", target_name="app")],
                output_filename="app.pex",
                internal_only=True,
                warn_for_transitive_files_targets=True,
            )
        ],
    )

    assert "The target //:app (`python_source`) transitively depends on" in caplog.text
    # files are not fine:
    assert "//:file_target" in caplog.text
    # resources are fine:
    assert "resource_target" not in caplog.text
    assert "resource.txt" not in caplog.text
