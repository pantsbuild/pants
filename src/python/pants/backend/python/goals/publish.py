# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.python.subsystems.setuptools import PythonDistributionFieldSet
from pants.backend.python.subsystems.twine import TwineSubsystem
from pants.backend.python.target_types import PythonDistribution
from pants.backend.python.util_rules.pex import (
    VenvPexProcess,
    create_venv_pex,
    setup_venv_pex_process,
)
from pants.core.goals.package import PackageFieldSet
from pants.core.goals.publish import (
    CheckSkipRequest,
    CheckSkipResult,
    PublishFieldSet,
    PublishOutputData,
    PublishPackages,
    PublishProcesses,
    PublishRequest,
)
from pants.core.util_rules.config_files import ConfigFiles, find_config_file
from pants.core.util_rules.env_vars import environment_vars_subset
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import CreateDigest, MergeDigests, Snapshot
from pants.engine.intrinsics import digest_to_snapshot, merge_digests
from pants.engine.process import InteractiveProcess
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import BoolField, StringSequenceField
from pants.engine.unions import UnionRule
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

    def make_skip_request(self, package_fs: PackageFieldSet) -> PythonDistCheckSkipRequest | None:
        return PythonDistCheckSkipRequest(publish_fs=self, package_fs=package_fs)

    def get_output_data(self) -> PublishOutputData:
        return PublishOutputData(
            {
                "publisher": "twine",
                **super().get_output_data(),
            }
        )


class PythonDistCheckSkipRequest(CheckSkipRequest[PublishPythonPackageFieldSet]):
    pass


@rule
async def check_if_skip_upload(
    request: PythonDistCheckSkipRequest, twine_subsystem: TwineSubsystem
) -> CheckSkipResult:
    if twine_subsystem.skip:
        reason = f"(by `[{TwineSubsystem.name}].skip = True`)"
    elif request.publish_fs.skip_twine.value:
        reason = f"(by `{request.publish_fs.skip_twine.alias}` on {request.address})"
    elif not request.publish_fs.repositories.value:
        reason = f"(no `{request.publish_fs.repositories.alias}` specified for {request.address})"
    else:
        return CheckSkipResult.no_skip()
    name = (
        request.package_fs.provides.value.kwargs.get("name", "<unknown python artifact>")
        if isinstance(request.package_fs, PythonDistributionFieldSet)
        else "<unknown artifact>"
    )
    return CheckSkipResult.skip(
        names=[name],
        description=reason,
        data=request.publish_fs.get_output_data(),
    )


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

    if not dists:
        return PublishProcesses()

    twine_pex, packages_digest, config_files = await concurrently(
        create_venv_pex(**implicitly(twine_subsystem.to_pex_request())),
        merge_digests(MergeDigests(pkg.digest for pkg in request.packages)),
        find_config_file(twine_subsystem.config_request()),
    )

    ca_cert_request = twine_subsystem.ca_certs_digest_request(global_options.ca_certs_path)
    ca_cert = (
        await digest_to_snapshot(**implicitly({ca_cert_request: CreateDigest}))
        if ca_cert_request
        else None
    )
    ca_cert_digest = (ca_cert.digest,) if ca_cert else ()

    input_digest = await merge_digests(
        MergeDigests((packages_digest, config_files.snapshot.digest, *ca_cert_digest))
    )
    pex_proc_requests: list[VenvPexProcess] = []
    twine_envs = await concurrently(
        environment_vars_subset(**implicitly({twine_env_request(repo): EnvironmentVarsRequest}))
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

    processes = await concurrently(
        setup_venv_pex_process(request, **implicitly()) for request in pex_proc_requests
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
        UnionRule(CheckSkipRequest, PythonDistCheckSkipRequest),
    )
