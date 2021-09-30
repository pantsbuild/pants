# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
import logging

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript, PythonDistribution
from pants.backend.python.util_rules.pex import PexRequest, PexRequirements, VenvPex, VenvPexProcess
from pants.core.goals.publish import (
    PublishFieldSet,
    PublishPackagesProcesses,
    PublishPackageProcesses,
    PublishPackagesRequest,
)
from pants.engine.fs import Digest, MergeDigests
from pants.engine.environment import Environment, InterpolatedEnvironmentRequest
from pants.engine.process import InteractiveProcess, Process
from pants.engine.rules import Get, collect_rules, rule, MultiGet
from pants.engine.target import StringField, StringSequenceField
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


class Twine(PythonToolBase):
    options_scope = "twine"
    help = "The utility for publishing Python distributions to PyPi and other Python repositories."
    default_version = "twine==3.4.2"
    default_main = ConsoleScript("twine")
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]


class PyPiRepositories(StringSequenceField):
    alias = "pypi_repositories"
    help = "List of PyPi repositories to publish the target package to."


class PublishToPyPiRequest(PublishPackagesRequest):
    pass


@dataclass(frozen=True)
class PublishToPyPiFieldSet(PublishFieldSet):
    publish_request_type = PublishToPyPiRequest
    required_fields = (PyPiRepositories,)

    repositories: PyPiRepositories


@rule
async def publish_to_pypi(request: PublishToPyPiRequest, twine: Twine) -> PublishPackagesProcesses:
    twine_pex, digest = await MultiGet(
        Get(
            VenvPex,
            PexRequest(
                output_filename="twine.pex",
                internal_only=True,
                requirements=PexRequirements(twine.all_requirements),
                main=twine.main,
            ),
        ),
        Get(Digest, MergeDigests(pkg.digest for pkg in request.packages)),
    )

    #args = ["--non-interactive"]
    args = ["check"]
    dists = [artifact.relpath for pkg in request.packages for artifact in pkg.artifacts]

    if not dists:
        return PublishPackagesProcesses(())

    process = await Get(
        Process,
        VenvPexProcess,
        VenvPexProcess(
            twine_pex,
            argv=args + dists,
            input_digest=digest,
            #extra_env=call_args.env,
            description=f"Checking {', '.join(dists)} to 'registry' (TODO)..",
        ),
    )

    return PublishPackagesProcesses((
        PublishPackageProcesses(
            tuple(dists),
            (
                InteractiveProcess.from_process(process),
            ),
        ),
    ))


def rules():
    return (
        *collect_rules(),
        PythonDistribution.register_plugin_field(PyPiRepositories),
        *PublishToPyPiFieldSet.rules(),
    )
