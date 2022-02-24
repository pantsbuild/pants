# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePath
from textwrap import dedent
from typing import Any, Dict, Iterable, List, cast

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    PythonRequirementsField,
    PythonRequirementTarget,
    PythonResolveField,
    PythonSourceField,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestTarget,
)
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.pex import Pex, PexPlatforms, PexRequest
from pants.backend.python.util_rules.pex_from_targets import (
    ChosenPythonResolve,
    ChosenPythonResolveRequest,
    GlobalRequirementConstraints,
    NoCompatibleResolveException,
    PexFromTargetsRequest,
)
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.build_graph.address import Address
from pants.engine.addresses import Addresses
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error
from pants.util.contextutil import pushd
from pants.util.ordered_set import OrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *pex_from_targets.rules(),
            *target_types_rules.rules(),
            QueryRule(PexRequest, (PexFromTargetsRequest,)),
            QueryRule(GlobalRequirementConstraints, ()),
            QueryRule(ChosenPythonResolve, [ChosenPythonResolveRequest]),
        ],
        target_types=[
            PythonSourcesGeneratorTarget,
            PythonRequirementTarget,
            PythonSourceTarget,
            PythonTestTarget,
        ],
    )


def test_no_compatible_resolve_error() -> None:
    python_setup = create_subsystem(PythonSetup, resolves={"a": "", "b": ""}, enable_resolves=True)
    targets = [
        PythonRequirementTarget(
            {PythonRequirementsField.alias: [], PythonResolveField.alias: "a"},
            Address("", target_name="t1"),
        ),
        PythonSourceTarget(
            {PythonSourceField.alias: "f.py", PythonResolveField.alias: "a"},
            Address("", target_name="t2"),
        ),
        PythonSourceTarget(
            {PythonSourceField.alias: "f.py", PythonResolveField.alias: "b"},
            Address("", target_name="t3"),
        ),
    ]
    assert str(NoCompatibleResolveException(python_setup, "Prefix", targets)).startswith(
        dedent(
            """\
            Prefix:

            a:
              * //:t1
              * //:t2

            b:
              * //:t3
            """
        )
    )


def test_choose_compatible_resolve(rule_runner: RuleRunner) -> None:
    def create_target_files(
        directory: str, *, req_resolve: str, source_resolve: str, test_resolve: str
    ) -> dict[str | PurePath, str | bytes]:
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


@dataclass(frozen=True)
class Project:
    name: str
    version: str


build_deps = ["setuptools==54.1.2", "wheel==0.36.2"]


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


def info(rule_runner: RuleRunner, pex: Pex) -> dict[str, Any]:
    rule_runner.scheduler.write_digest(pex.digest)
    completed_process = subprocess.run(
        args=[
            sys.executable,
            "-m",
            "pex.tools",
            pex.name,
            "info",
        ],
        cwd=rule_runner.build_root,
        stdout=subprocess.PIPE,
        check=True,
    )
    return cast(Dict[str, Any], json.loads(completed_process.stdout))


def requirements(rule_runner: RuleRunner, pex: Pex) -> list[str]:
    return cast(List[str], info(rule_runner, pex)["requirements"])


def test_constraints_validation(tmp_path: Path, rule_runner: RuleRunner) -> None:
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
            "BUILD": dedent(
                f"""
                python_requirement(name="foo", requirements=["foo-bar>=0.1.2"])
                python_requirement(name="bar", requirements=["bar==5.5.5"])
                python_requirement(name="baz", requirements=["baz"])
                python_requirement(name="foorl", requirements=["{url_req}"])
                python_sources(name="util", sources=[], dependencies=[":foo", ":bar"])
                python_sources(name="app", sources=[], dependencies=[":util", ":baz", ":foorl"])
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
        additional_args: Iterable[str] = (),
        additional_lockfile_args: Iterable[str] = (),
    ) -> PexRequest:
        args = ["--backend-packages=pants.backend.python"]
        request = PexFromTargetsRequest(
            [Address("", target_name="app")],
            output_filename="demo.pex",
            internal_only=True,
            additional_args=additional_args,
            additional_lockfile_args=additional_lockfile_args,
        )
        if resolve_all_constraints is not None:
            args.append(f"--python-resolve-all-constraints={resolve_all_constraints!r}")
        if constraints_file:
            args.append(f"--python-requirement-constraints={constraints_file}")
        args.append("--python-repos-indexes=[]")
        args.append(f"--python-repos-repos={find_links}")
        rule_runner.set_options(args, env_inherit={"PATH"})
        pex_request = rule_runner.request(PexRequest, [request])
        assert OrderedSet(additional_args).issubset(OrderedSet(pex_request.additional_args))
        return pex_request

    additional_args = ["--strip-pex-env"]
    additional_lockfile_args = ["--no-strip-pex-env"]

    pex_req1 = get_pex_request(constraints1_filename, resolve_all_constraints=False)
    assert pex_req1.requirements == PexRequirements(
        ["foo-bar>=0.1.2", "bar==5.5.5", "baz", url_req],
        constraints_strings=constraints1_strings,
    )

    pex_req2 = get_pex_request(
        constraints1_filename,
        resolve_all_constraints=True,
        additional_args=additional_args,
        additional_lockfile_args=additional_lockfile_args,
    )
    pex_req2_reqs = pex_req2.requirements
    assert isinstance(pex_req2_reqs, PexRequirements)
    assert list(pex_req2_reqs.req_strings) == ["bar==5.5.5", "baz", "foo-bar>=0.1.2", url_req]
    assert pex_req2_reqs.repository_pex is not None
    assert not info(rule_runner, pex_req2_reqs.repository_pex)["strip_pex_env"]
    repository_pex = pex_req2_reqs.repository_pex
    assert ["Foo._-BAR==1.0.0", "bar==5.5.5", "baz==2.2.2", "foorl", "qux==3.4.5"] == requirements(
        rule_runner, repository_pex
    )

    with engine_error(
        ValueError,
        contains=(
            "`[python].resolve_all_constraints` is enabled, so "
            "`[python].requirement_constraints` must also be set."
        ),
    ):
        get_pex_request(None, resolve_all_constraints=True)

    # Shouldn't error, as we don't explicitly set --resolve-all-constraints.
    get_pex_request(None, resolve_all_constraints=None)


@pytest.mark.parametrize("include_requirements", [False, True])
def test_exclude_requirements(
    include_requirements: bool, tmp_path: Path, rule_runner: RuleRunner
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
    assert len(pex_request.requirements.req_strings) == (1 if include_requirements else 0)


def test_issue_12222(rule_runner: RuleRunner) -> None:
    constraints = ["foo==1.0", "bar==1.0"]
    rule_runner.write_files(
        {
            "constraints.txt": "\n".join(constraints),
            "BUILD": dedent(
                """
                python_requirement(name="foo",requirements=["foo"])
                python_requirement(name="bar",requirements=["bar"])
                python_sources(name="lib",sources=[],dependencies=[":foo"])
                """
            ),
        }
    )
    request = PexFromTargetsRequest(
        [Address("", target_name="lib")],
        output_filename="demo.pex",
        internal_only=False,
        platforms=PexPlatforms(["some-platform-x86_64"]),
    )
    rule_runner.set_options(
        [
            "--python-requirement-constraints=constraints.txt",
            "--python-resolve-all-constraints",
        ]
    )
    result = rule_runner.request(PexRequest, [request])

    assert result.requirements == PexRequirements(["foo"], constraints_strings=constraints)
