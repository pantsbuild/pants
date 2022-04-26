# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import PurePath

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
from pants.base.specs import AddressSpecs
from pants.base.specs_parser import SpecsParser
from pants.core.goals.tailor import group_by_dir
from pants.core.goals.test import TestExtraEnv
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.collection import DeduplicatedCollection
from pants.engine.console import Console
from pants.engine.fs import CreateDigest, DigestContents, FileContent, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.native_engine import Digest, MergeDigests, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import Targets, TransitiveTargets, TransitiveTargetsRequest
from pants.jvm.resolve.common import ArtifactRequirement, ArtifactRequirements
from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.testutil.lockfile_fixture import JVMLockfileFixtureDefinition
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel

COLLECTION_SCRIPT = r"""\
from pathlib import Path
import json
import sys

import pytest

class CollectionPlugin:
    def __init__(self):
        self.collected = []

    def pytest_collection_modifyitems(self, items):
        for item in items:
            self.collected.append(item)


collection_plugin = CollectionPlugin()
pytest.main(["--collect-only", "src/python/pants"], plugins=[collection_plugin])
output = []
cwd = Path.cwd()
for item in collection_plugin.collected:
    mark = item.get_closest_marker("jvm_lockfile")
    if not mark:
        continue

    path = Path(item.path).relative_to(cwd)

    output.append({
        "kwargs": mark.kwargs,
        "test_file_path": str(path),
    })

with open("tests.json", "w") as f:
    f.write(json.dumps(output))
"""


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


@dataclass(frozen=True)
class CollectFixtureConfigsRequest:
    pass


# TODO: This rule was mostly copied from the rule `setup_pytest_for_target` in
# `src/python/pants/backend/python/goals/pytest_runner.py`. Some refactoring should be done.
@rule
async def collect_fixture_configs(
    _request: CollectFixtureConfigsRequest,
    pytest: PyTest,
    python_setup: PythonSetup,
    test_extra_env: TestExtraEnv,
) -> CollectedJVMLockfileFixtureConfigs:
    specs_parser = SpecsParser()
    specs = specs_parser.parse_specs(["src/python/pants::"])
    targets = await Get(Targets, AddressSpecs, specs.address_specs)
    addresses = [tgt.address for tgt in targets]
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(addresses))
    all_targets = transitive_targets.closure

    interpreter_constraints = InterpreterConstraints.create_from_targets(all_targets, python_setup)

    requirements_pex_get = Get(Pex, RequirementsPexRequest(addresses))
    pytest_pex_get = Get(
        Pex,
        PexRequest(
            output_filename="pytest.pex",
            requirements=pytest.pex_requirements(),
            interpreter_constraints=interpreter_constraints,
            internal_only=True,
        ),
    )

    prepared_sources_get = Get(
        PythonSourceFiles, PythonSourceFilesRequest(all_targets, include_files=True)
    )

    (pytest_pex, requirements_pex, prepared_sources,) = await MultiGet(
        pytest_pex_get,
        requirements_pex_get,
        prepared_sources_get,
    )

    script_content = FileContent(
        path="collect-fixtures.py", content=COLLECTION_SCRIPT.encode(), is_executable=True
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
            argv=[*prepared_sources.source_files.files],
            extra_env=extra_env,
            input_digest=input_digest,
            output_files=("tests.json",),
            description="Collect test lockfile requirements from all tests.",
            level=LogLevel.DEBUG,
        ),
    )

    result = await Get(ProcessResult, Process, process)
    digest_contents = await Get(DigestContents, Digest, result.output_digest)
    raw_config_data = json.loads(digest_contents[0].content)

    configs = []
    for item in raw_config_data:
        config = JVMLockfileFixtureConfig(
            definition=JVMLockfileFixtureDefinition.from_kwargs(item["kwargs"]),
            test_file_path=item["test_file_path"],
        )
        configs.append(config)

    return CollectedJVMLockfileFixtureConfigs(configs)


@rule
async def gather_lockfile_fixtures() -> RenderedJVMLockfileFixtures:
    configs = await Get(CollectedJVMLockfileFixtureConfigs, CollectFixtureConfigsRequest())
    rendered_fixtures = []
    for config in configs:
        artifact_reqs = ArtifactRequirements(
            [ArtifactRequirement(coordinate) for coordinate in config.definition.coordinates]
        )
        lockfile = await Get(CoursierResolvedLockfile, ArtifactRequirements, artifact_reqs)
        serialized_lockfile = JVMLockfileMetadata.new(artifact_reqs).add_header_to_lockfile(
            lockfile.to_serialized(),
            regenerate_command=f"{bin_name()} {InternalGenerateTestLockfileFixturesSubsystem.name}",
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


@goal_rule
async def internal_render_test_lockfile_fixtures(
    rendered_fixtures: RenderedJVMLockfileFixtures,
    workspace: Workspace,
    console: Console,
) -> InternalGenerateTestLockfileFixturesGoal:
    if not rendered_fixtures:
        console.write_stdout("No test lockfile fixtures found.")
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
