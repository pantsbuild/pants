# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.python.subsystems.twine import TwineSubsystem
from pants.backend.python.target_types import PythonDistribution
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.publish import (
    PublishFieldSet,
    PublishPackageProcesses,
    PublishPackagesProcesses,
    PublishPackagesRequest,
)
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import InteractiveProcess, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import StringSequenceField, Target

logger = logging.getLogger(__name__)


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

    # I'd rather opt out early here, so we don't build unnecessarily, however the error feedback is
    # misleading and not very helpful in that case.
    #
    # @classmethod
    # def opt_out(cls, tgt: Target) -> bool:
    #     return not tgt[PyPiRepositories].value


def twine_upload_args(
    twine_subsystem: TwineSubsystem, config_files: ConfigFiles, repo: str, dists: tuple[str, ...]
) -> tuple[str, ...]:
    args = ["upload", "--non-interactive"]

    if config_files.snapshot.files:
        args.append(f"--config-file={config_files.snapshot.files[0]}")

    args.extend(twine_subsystem.args)

    if repo.startswith("@"):
        # Named repository from the config file.
        args.append(f"--repository={repo[1:]}")
    else:
        args.append(f"--repository-url={repo}")

    args.extend(dists)
    return tuple(args)


@rule
async def twine_upload(
    request: PublishToPyPiRequest, twine_subsystem: TwineSubsystem
) -> PublishPackagesProcesses:
    dists = tuple(
        artifact.relpath
        for pkg in request.packages
        for artifact in pkg.artifacts
        if artifact.relpath
    )

    if twine_subsystem.skip or not dists:
        return PublishPackagesProcesses(())

    if not request.field_set.repositories.value:
        # I'd rather have used the opt_out mechanism on the field set, but that gives no hint as to
        # why the target was not applicable..
        return PublishPackagesProcesses((
            PublishPackageProcesses(
                names=dists,
                description=f"(no `{request.field_set.repositories.alias}` specifed for {request.field_set.address})"
            ),
        ))

    twine_pex, packages_digest, config_files = await MultiGet(
        Get(
            VenvPex,
            PexRequest(
                output_filename="twine.pex",
                internal_only=True,
                requirements=twine_subsystem.pex_requirements(),
                interpreter_constraints=twine_subsystem.interpreter_constraints,
                main=twine_subsystem.main,
            ),
        ),
        Get(Digest, MergeDigests(pkg.digest for pkg in request.packages)),
        Get(ConfigFiles, ConfigFilesRequest, twine_subsystem.config_request()),
    )

    input_digest = await Get(Digest, MergeDigests((packages_digest, config_files.snapshot.digest)))
    pex_proc_requests = []

    for repo in request.field_set.repositories.value:
        pex_proc_requests.append(
            VenvPexProcess(
                twine_pex,
                argv=twine_upload_args(twine_subsystem, config_files, repo, dists),
                input_digest=input_digest,
                # extra_env=call_args.env,
                description=repo,
            )
        )

    processes = await MultiGet(
        Get(Process, VenvPexProcess, request) for request in pex_proc_requests
    )

    return PublishPackagesProcesses(
        tuple(
            PublishPackageProcesses(
                names=dists,
                processes=(InteractiveProcess.from_process(process),),
                description=process.description,
            )
            for process in processes
        )
    )


def rules():
    return (
        *collect_rules(),
        PythonDistribution.register_plugin_field(PyPiRepositories),
        *PublishToPyPiFieldSet.rules(),
    )
