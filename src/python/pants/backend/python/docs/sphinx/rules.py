# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.docs.sphinx.sphinx_subsystem import SphinxSubsystem
from pants.backend.python.docs.sphinx.target_types import SphinxProjectSourcesField
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.util_rules.distdir import DistDir
from pants.engine.addresses import Address
from pants.engine.fs import Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest, WrappedTarget
from pants.util.logging import LogLevel


class SphinxDocsGoalSubsystem(GoalSubsystem):
    name = "sphinx-docs"
    help = "Generate docs with Sphinx"


class SphinxDocsGoal(Goal):
    subsystem_cls = SphinxDocsGoalSubsystem


@goal_rule
async def generate_sphinx_docs(
    sphinx: SphinxSubsystem, dist_dir: DistDir, workspace: Workspace
) -> SphinxDocsGoal:
    wrapped_tgt = await Get(WrappedTarget, Address("sphinx-demo", target_name="sphinx"))
    tgt = wrapped_tgt.target
    sources = await Get(HydratedSources, HydrateSourcesRequest(tgt[SphinxProjectSourcesField]))
    sphinx_pex = await Get(VenvPex, PexRequest, sphinx.to_pex_request())

    result = await Get(
        ProcessResult,
        VenvPexProcess(
            sphinx_pex,
            argv=(tgt.address.spec_path or ".", "__build"),
            output_directories=("__build",),
            input_digest=sources.snapshot.digest,
            description=f"Generate docs with Sphinx for {tgt.address}",
            level=LogLevel.DEBUG,
        ),
    )
    workspace.write_digest(result.output_digest, path_prefix=str(dist_dir.relpath))
    return SphinxDocsGoal(exit_code=0)


def rules():
    return collect_rules()
