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
    PublishOutputData,
    PublishPackages,
    PublishProcesses,
    PublishRequest,
)
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import CreateDigest, Digest, MergeDigests, Snapshot
from pants.engine.process import InteractiveProcess, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import BoolField, StringSequenceField
from pants.option.global_options import GlobalOptions
from pants.util.strutil import help_text

logger = logging.getLogger(__name__)


class PythonRepositoriesField(StringSequenceField):
    alias = "repositories"
    help = help_text(
        """
        List of URL addresses or Twine repository aliases where to publish the Python package.

        Twine is used for publishing Python packages, so the address to any kind of repository
        that Twine supports may be used here.

        Aliases are prefixed with `@` to refer to a config section in your Twine configuration,
        such as a `.pypirc` file. Use `@pypi` to upload to the public PyPi repository, which is
        the default when using Twine directly.
        """
    )

    # Twine uploads to 'pypi' by default, but we don't set default to ["@pypi"] here to make it
    # explicit in the BUILD file when a package is meant for public distribution.


class SkipTwineUploadField(BoolField):
    alias = "skip_twine"
    default = False
    help = "If true, don't publish this target's packages using Twine."


class PublishPythonPackageRequest(PublishRequest):
    pass


@dataclass(frozen=True)
class PublishPythonPackageFieldSet(PublishFieldSet):
    publish_request_type = PublishPythonPackageRequest
    required_fields = (PythonRepositoriesField,)

    repositories: PythonRepositoriesField
    skip_twine: SkipTwineUploadField

    def get_output_data(self) -> PublishOutputData:
        return PublishOutputData(
            {
                "publisher": "twine",
                **super().get_output_data(),
            }
        )

    # I'd rather opt out early here, so we don't build unnecessarily, however the error feedback is
    # misleading and not very helpful in that case.
    #
    # @classmethod
    # def opt_out(cls, tgt: Target) -> bool:
    #     return not tgt[PythonRepositoriesField].value


def twine_upload_args(
    twine_subsystem: TwineSubsystem,
    config_files: ConfigFiles,
    repo: str,
    dists: tuple[str, ...],
    ca_cert: Snapshot | None,
) -> tuple[str, ...]:
    args = ["upload", "--non-interactive"]

    if ca_cert and ca_cert.files:
        args.append(f"--cert={ca_cert.files[0]}")

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


def twine_env_suffix(repo: str) -> str:
    return f"_{repo[1:]}".replace("-", "_").upper() if repo.startswith("@") else ""


def twine_env_request(repo: str) -> EnvironmentVarsRequest:
    suffix = twine_env_suffix(repo)
    env_vars = [
        "TWINE_USERNAME",
        "TWINE_PASSWORD",
        "TWINE_REPOSITORY_URL",
    ]
    req = EnvironmentVarsRequest(env_vars + [f"{var}{suffix}" for var in env_vars])
    return req


def twine_env(env: EnvironmentVars, repo: str) -> EnvironmentVars:
    suffix = twine_env_suffix(repo)
    return EnvironmentVars(
        {key.rsplit(suffix, maxsplit=1)[0] if suffix else key: value for key, value in env.items()}
    )


@rule
async def twine_upload(
    request: PublishPythonPackageRequest,
    twine_subsystem: TwineSubsystem,
    global_options: GlobalOptions,
) -> PublishProcesses:
    dists = tuple(
        artifact.relpath
        for pkg in request.packages
        for artifact in pkg.artifacts
        if artifact.relpath
    )

    if twine_subsystem.skip or not dists:
        return PublishProcesses()

    # Too verbose to provide feedback as to why some packages were skipped?
    skip = None
    if request.field_set.skip_twine.value:
        skip = f"(by `{request.field_set.skip_twine.alias}` on {request.field_set.address})"
    elif not request.field_set.repositories.value:
        # I'd rather have used the opt_out mechanism on the field set, but that gives no hint as to
        # why the target was not applicable..
        skip = f"(no `{request.field_set.repositories.alias}` specified for {request.field_set.address})"

    if skip:
        return PublishProcesses(
            [
                PublishPackages(
                    names=dists,
                    description=skip,
                ),
            ]
        )

    twine_pex, packages_digest, config_files = await MultiGet(
        Get(VenvPex, PexRequest, twine_subsystem.to_pex_request()),
        Get(Digest, MergeDigests(pkg.digest for pkg in request.packages)),
        Get(ConfigFiles, ConfigFilesRequest, twine_subsystem.config_request()),
    )

    ca_cert_request = twine_subsystem.ca_certs_digest_request(global_options.ca_certs_path)
    ca_cert = await Get(Snapshot, CreateDigest, ca_cert_request) if ca_cert_request else None
    ca_cert_digest = (ca_cert.digest,) if ca_cert else ()

    input_digest = await Get(
        Digest, MergeDigests((packages_digest, config_files.snapshot.digest, *ca_cert_digest))
    )
    pex_proc_requests = []
    twine_envs = await MultiGet(
        Get(EnvironmentVars, EnvironmentVarsRequest, twine_env_request(repo))
        for repo in request.field_set.repositories.value
    )

    for repo, env in zip(request.field_set.repositories.value, twine_envs):
        pex_proc_requests.append(
            VenvPexProcess(
                twine_pex,
                argv=twine_upload_args(twine_subsystem, config_files, repo, dists, ca_cert),
                input_digest=input_digest,
                extra_env=twine_env(env, repo),
                description=repo,
            )
        )

    processes = await MultiGet(
        Get(Process, VenvPexProcess, request) for request in pex_proc_requests
    )

    return PublishProcesses(
        PublishPackages(
            names=dists,
            process=InteractiveProcess.from_process(process),
            description=process.description,
            data=PublishOutputData({"repository": process.description}),
        )
        for process in processes
    )


def rules():
    return (
        *collect_rules(),
        *PublishPythonPackageFieldSet.rules(),
        PythonDistribution.register_plugin_field(PythonRepositoriesField),
        PythonDistribution.register_plugin_field(SkipTwineUploadField),
    )
