# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript, PythonDistribution
from pants.backend.python.util_rules.pex import PexRequest, PexRequirements, VenvPex, VenvPexProcess
from pants.core.goals.publish import (
    PublishProcess,
    PublishRequest,
    PublishTarget,
    PublishTargetField,
)
from pants.engine.environment import Environment, InterpolatedEnvironmentRequest
from pants.engine.process import InteractiveProcess, Process
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import StringField
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


class Twine(PythonToolBase):
    options_scope = "twine"
    help = "The utility for publishing Python pakcages to PyPi and other repositories."
    default_version = "twine==3.4.2"
    default_main = ConsoleScript("twine")
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]


class PypiRepositoryName(StringField):
    alias = "repository"
    help = "The pypi repository to upload the package to."
    default = "pypi"


class PypiRepositoryUrl(StringField):
    alias = "repository_url"
    help = "The pypi repository url to upload the package to. Takes priority over `repository`."


class PypiRepositoryUsername(StringField):
    alias = "username"
    help = "The username for this repository. Suppirting ${BASH_STYLE} environment interpolation."
    default = "${TWINE_USERNAME}"


class PypiRepositoryPassword(StringField):
    alias = "password"
    help = "The password for this repository. Supporting ${BASH_STYLE} environment interpolation."
    default = "${TWINE_PASSWORD}"


class PypiPublishRequest(PublishRequest):
    pass


class PypiRepositoryTarget(PublishTarget):
    alias = "pypi_repository"
    help = "A pypi repository."

    core_fields = (
        *PublishTarget.core_fields,
        PypiRepositoryName,
        PypiRepositoryUrl,
        PypiRepositoryUsername,
        PypiRepositoryPassword,
    )
    publish_request_type = PypiPublishRequest


@dataclass(frozen=True)
class TwineCallArgs:
    args: FrozenOrderedSet
    env: FrozenDict[str, str]


@rule
async def twine_call_args(target: PypiRepositoryTarget) -> TwineCallArgs:
    env = await Get(
        Environment,
        InterpolatedEnvironmentRequest(
            {
                "TWINE_USERNAME": target[PypiRepositoryUsername].value,
                "TWINE_PASSWORD": target[PypiRepositoryPassword].value,
            }
        ),
    )

    args = ["--non-interactive"]

    repo_name = target[PypiRepositoryName].value
    repo_url = target[PypiRepositoryUrl].value
    if repo_url:
        args += ["--repository-url", repo_url]
    else:
        args += ["-r", repo_name]

    return TwineCallArgs(FrozenOrderedSet(args), env)


@rule
async def publish_pypi(request: PypiPublishRequest, twine: Twine) -> PublishProcess:
    twine_pex = await Get(
        VenvPex,
        PexRequest(
            output_filename="twine.pex",
            internal_only=True,
            requirements=PexRequirements(twine.all_requirements),
            main=twine.main,
        ),
    )

    call_args = await Get(TwineCallArgs, PypiRepositoryTarget, request.publish_target)
    paths = [artifact.relpath for artifact in request.built_package.artifacts]

    if not paths:
        return PublishProcess(process=None, message="No artifacts found.")

    process = await Get(
        Process,
        VenvPexProcess,
        VenvPexProcess(
            twine_pex,
            argv=["upload", *call_args.args, *paths],
            input_digest=request.built_package.digest,
            extra_env=call_args.env,
            description=f"Publishing {', '.join(paths)} to {request.publish_target.address}.",
        ),
    )

    return PublishProcess(process=InteractiveProcess.from_process(process))


def rules():
    return [
        *collect_rules(),
        PythonDistribution.register_plugin_field(PublishTargetField),
        UnionRule(PublishRequest, PypiPublishRequest),
    ]
