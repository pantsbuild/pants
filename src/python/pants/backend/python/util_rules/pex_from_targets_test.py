# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePath
from textwrap import dedent
from typing import List, Optional, cast

import pytest
from _pytest.tmpdir import TempPathFactory

from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.pex import Pex, PexRequest, PexRequirements
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.build_graph.address import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.python.python_setup import ResolveAllConstraintsOption
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *pex_from_targets.rules(),
            QueryRule(PexRequest, (PexFromTargetsRequest,)),
        ],
        target_types=[PythonLibrary, PythonRequirementLibrary],
    )


@dataclass(frozen=True)
class Project:
    name: str
    version: str


def create_dists(workdir: Path, project: Project, *projects: Project) -> PurePath:
    project_dirs = []
    for proj in (project, *projects):
        project_dir = workdir / "projects" / proj.name
        project_dir.mkdir(parents=True)
        project_dirs.append(project_dir)

        (project_dir / "pyproject.toml").write_text(
            dedent(
                """\
                [build-system]
                requires = ["setuptools==54.1.2", "wheel==0.36.2"]
                build-backend = "setuptools.build_meta"
                """
            )
        )
        (project_dir / "setup.cfg").write_text(
            dedent(
                f"""\
                [metadata]
                name = {proj.name}
                version = {proj.version}
                """
            )
        )

    pex = workdir / "pex"
    subprocess.run(
        args=[sys.executable, "-m", "pex", *project_dirs, "--include-tools", "-o", pex], check=True
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


def requirements(rule_runner: RuleRunner, pex: Pex) -> List[str]:
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
    return cast(List[str], json.loads(completed_process.stdout.decode())["requirements"])


def test_constraints_validation(tmp_path_factory: TempPathFactory, rule_runner: RuleRunner) -> None:
    find_links = create_dists(
        tmp_path_factory.mktemp("sdists"),
        Project("Foo-Bar", "1.0.0"),
        Project("Bar", "5.5.5"),
        Project("baz", "2.2.2"),
        Project("QUX", "3.4.5"),
    )

    rule_runner.add_to_build_file(
        "",
        dedent(
            """
            python_requirement_library(name="foo", requirements=["foo-bar>=0.1.2"])
            python_requirement_library(name="bar", requirements=["bar==5.5.5"])
            python_requirement_library(name="baz", requirements=["baz"])
            python_library(name="util", sources=[], dependencies=[":foo", ":bar"])
            python_library(name="app", sources=[], dependencies=[":util", ":baz"])
            """
        ),
    )
    rule_runner.create_file(
        "constraints1.txt",
        dedent(
            """
            # Comment.
            --find-links=https://duckduckgo.com
            Foo._-BAR==1.0.0  # Inline comment.
            bar==5.5.5
            baz==2.2.2
            qux==3.4.5
        """
        ),
    )

    def get_pex_request(
        constraints_file: Optional[str],
        resolve_all: Optional[ResolveAllConstraintsOption],
        *,
        direct_deps_only: bool = False,
    ) -> PexRequest:
        args = ["--backend-packages=pants.backend.python"]
        request = PexFromTargetsRequest(
            [Address("", target_name="app")],
            output_filename="demo.pex",
            internal_only=True,
            direct_deps_only=direct_deps_only,
        )
        if resolve_all:
            args.append(f"--python-setup-resolve-all-constraints={resolve_all.value}")
        if constraints_file:
            args.append(f"--python-setup-requirement-constraints={constraints_file}")
        args.append("--python-repos-indexes=[]")
        args.append(f"--python-repos-repos={find_links}")
        rule_runner.set_options(args, env_inherit={"PATH"})
        return rule_runner.request(PexRequest, [request])

    pex_req1 = get_pex_request("constraints1.txt", ResolveAllConstraintsOption.NEVER)
    assert pex_req1.requirements == PexRequirements(["foo-bar>=0.1.2", "bar==5.5.5", "baz"])
    assert pex_req1.repository_pex is None

    pex_req1_direct = get_pex_request(
        "constraints1.txt", ResolveAllConstraintsOption.NEVER, direct_deps_only=True
    )
    assert pex_req1_direct.requirements == PexRequirements(["baz"])
    assert pex_req1_direct.repository_pex is None

    pex_req2 = get_pex_request("constraints1.txt", ResolveAllConstraintsOption.ALWAYS)
    assert pex_req2.requirements == PexRequirements(["foo-bar>=0.1.2", "bar==5.5.5", "baz"])
    assert pex_req2.repository_pex is not None
    repository_pex = pex_req2.repository_pex
    assert ["Foo._-BAR==1.0.0", "bar==5.5.5", "baz==2.2.2", "qux==3.4.5"] == requirements(
        rule_runner, repository_pex
    )

    pex_req2_direct = get_pex_request(
        "constraints1.txt", ResolveAllConstraintsOption.ALWAYS, direct_deps_only=True
    )
    assert pex_req2_direct.requirements == PexRequirements(["baz"])
    assert pex_req2_direct.repository_pex == repository_pex

    with pytest.raises(ExecutionError) as err:
        get_pex_request(None, ResolveAllConstraintsOption.ALWAYS)
    assert len(err.value.wrapped_exceptions) == 1
    assert isinstance(err.value.wrapped_exceptions[0], ValueError)
    assert (
        "[python-setup].resolve_all_constraints is set to always, so "
        "either [python-setup].requirement_constraints or "
        "[python-setup].requirement_constraints_target must also be provided."
    ) in str(err.value)

    # Shouldn't error, as we don't explicitly set --resolve-all-constraints.
    get_pex_request(None, None)
