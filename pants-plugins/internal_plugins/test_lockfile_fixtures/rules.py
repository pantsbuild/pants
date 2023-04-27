# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os
import pkgutil
from dataclasses import dataclass
from pathlib import PurePath

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import JVMLockfileFixtureDefinition
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.test import TestExtraEnv
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.collection import DeduplicatedCollection
from pants.engine.console import Console
from pants.engine.fs import CreateDigest, DigestContents, FileContent, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.native_engine import Digest, MergeDigests, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import Targets, TransitiveTargets, TransitiveTargetsRequest
from pants.jvm.resolve.common import ArtifactRequirement, ArtifactRequirements
from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.util.dirutil import group_by_dir
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class JVMLockfileFixtureConfig:
    definition: JVMLockfileFixtureDefinition
    test_file_path: str


class CollectedJVMLockfileFixtureConfigs(DeduplicatedCollection[JVMLockfileFixtureConfig]):
    pass


@dataclass(frozen=True)
class RenderedJVMLockfileFixture:
    content: bytes
    path: str


class RenderedJVMLockfileFixtures(DeduplicatedCollection[RenderedJVMLockfileFixture]):
    pass


# TODO: This rule was mostly copied from the rule `setup_pytest_for_target` in
# `src/python/pants/backend/python/goals/pytest_runner.py`. Some refactoring should be done.
@rule
async def collect_fixture_configs(
    pytest: PyTest,
    python_setup: PythonSetup,
    test_extra_env: TestExtraEnv,
    targets: Targets,
) -> CollectedJVMLockfileFixtureConfigs:
    addresses = [tgt.address for tgt in targets]
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(addresses))
    all_targets = transitive_targets.closure

    interpreter_constraints = InterpreterConstraints.create_from_targets(all_targets, python_setup)

    pytest_pex, requirements_pex, prepared_sources, root_sources = await MultiGet(
        Get(
            Pex,
            PexRequest,
            pytest.to_pex_request(interpreter_constraints=interpreter_constraints),
        ),
        Get(Pex, RequirementsPexRequest(addresses)),
        Get(
            PythonSourceFiles,
            PythonSourceFilesRequest(all_targets, include_files=True, include_resources=True),
        ),
        Get(
            PythonSourceFiles,
            PythonSourceFilesRequest(targets),
        ),
    )

    script_content_bytes = pkgutil.get_data(__name__, "collect_fixtures.py")
    if not script_content_bytes:
        raise AssertionError("Did not find collect_fixtures.py script as resouce.")
    script_content = FileContent(
        path="collect_fixtures.py",
        content=script_content_bytes,
        is_executable=True,
    )
    script_digest = await Get(Digest, CreateDigest([script_content]))

    pytest_runner_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="pytest_runner.pex",
            interpreter_constraints=interpreter_constraints,
            main=EntryPoint(PurePath(script_content.path).stem),
            sources=script_digest,
            internal_only=True,
            pex_path=[
                pytest_pex,
                requirements_pex,
            ],
        ),
    )
    config_file_dirs = list(group_by_dir(prepared_sources.source_files.files).keys())
    config_files_get = Get(
        ConfigFiles,
        ConfigFilesRequest,
        pytest.config_request(config_file_dirs),
    )
    pytest_runner_pex, config_files = await MultiGet(pytest_runner_pex_get, config_files_get)

    pytest_config_digest = config_files.snapshot.digest

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                prepared_sources.source_files.snapshot.digest,
                pytest_config_digest,
            )
        ),
    )

    extra_env = {
        "PEX_EXTRA_SYS_PATH": ":".join(prepared_sources.source_roots),
        **test_extra_env.env,
    }

    process = await Get(
        Process,
        VenvPexProcess(
            pytest_runner_pex,
            argv=[name for name in root_sources.source_files.files if name.endswith(".py")],
            extra_env=extra_env,
            input_digest=input_digest,
            output_files=("tests.json",),
            description="Collect test lockfile requirements from all tests.",
            level=LogLevel.DEBUG,
            cache_scope=ProcessCacheScope.PER_SESSION,
        ),
    )

    result = await Get(ProcessResult, Process, process)
    digest_contents = await Get(DigestContents, Digest, result.output_digest)
    assert len(digest_contents) == 1
    assert digest_contents[0].path == "tests.json"
    raw_config_data = json.loads(digest_contents[0].content)

    configs = []
    for item in raw_config_data:
        config = JVMLockfileFixtureConfig(
            definition=JVMLockfileFixtureDefinition.from_json_dict(item),
            test_file_path=item["test_file_path"],
        )
        configs.append(config)

    return CollectedJVMLockfileFixtureConfigs(configs)


@rule
async def gather_lockfile_fixtures(
    configs: CollectedJVMLockfileFixtureConfigs,
) -> RenderedJVMLockfileFixtures:
    rendered_fixtures = []
    for config in configs:
        artifact_reqs = ArtifactRequirements(
            [ArtifactRequirement(coordinate) for coordinate in config.definition.requirements]
        )
        lockfile = await Get(CoursierResolvedLockfile, ArtifactRequirements, artifact_reqs)
        serialized_lockfile = JVMLockfileMetadata.new(artifact_reqs).add_header_to_lockfile(
            lockfile.to_serialized(),
            regenerate_command=f"{bin_name()} {InternalGenerateTestLockfileFixturesSubsystem.name} ::",
            delimeter="#",
        )

        lockfile_path = os.path.join(
            os.path.dirname(config.test_file_path), config.definition.lockfile_rel_path
        )
        rendered_fixtures.append(
            RenderedJVMLockfileFixture(
                content=serialized_lockfile,
                path=lockfile_path,
            )
        )

    return RenderedJVMLockfileFixtures(rendered_fixtures)


class InternalGenerateTestLockfileFixturesSubsystem(GoalSubsystem):
    name = "internal-generate-test-lockfile-fixtures"
    help = "[Internal] Generate test lockfile fixtures for Pants tests."


class InternalGenerateTestLockfileFixturesGoal(Goal):
    subsystem_cls = InternalGenerateTestLockfileFixturesSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY  # TODO(#17129) — Migrate this.


@goal_rule
async def internal_render_test_lockfile_fixtures(
    rendered_fixtures: RenderedJVMLockfileFixtures,
    workspace: Workspace,
    console: Console,
) -> InternalGenerateTestLockfileFixturesGoal:
    if not rendered_fixtures:
        console.write_stdout("No test lockfile fixtures found.\n")
        return InternalGenerateTestLockfileFixturesGoal(exit_code=0)

    digest_contents = [
        FileContent(rendered_fixture.path, rendered_fixture.content)
        for rendered_fixture in rendered_fixtures
    ]
    snapshot = await Get(Snapshot, CreateDigest(digest_contents))
    console.write_stdout(f"Writing test lockfile fixtures: {snapshot.files}\n")
    workspace.write_digest(snapshot.digest)
    return InternalGenerateTestLockfileFixturesGoal(exit_code=0)


def rules():
    return collect_rules()
