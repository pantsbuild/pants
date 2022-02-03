# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.core.goals.package import BuiltPackage
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.native_engine import AddPrefix
from pants.engine.process import Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import JvmProcess
from pants.jvm.package.deploy_jar import DeployJarFieldSet
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@rule(level=LogLevel.DEBUG)
async def create_deploy_jar_run_request(
    field_set: DeployJarFieldSet,
) -> RunRequest:

    main_class = field_set.main_class.value
    assert main_class is not None

    package = await Get(BuiltPackage, DeployJarFieldSet, field_set)
    assert len(package.artifacts) == 1
    jar_path = package.artifacts[0].relpath
    assert jar_path is not None

    proc = await Get(
        Process,
        JvmProcess(
            classpath_entries=[f"{{chroot}}/{jar_path}"],
            argv=(main_class,),
            input_digest=package.digest,
            description=f"Run {main_class}.main(String[])",
            use_nailgun=False,
        ),
    )

    support_digests = await MultiGet(
        Get(Digest, AddPrefix(digest, prefix))
        for prefix, digest in proc.immutable_input_digests.items()
    )

    def prefixed(arg: str, needle: str = "__") -> str:
        if arg.startswith(needle):
            return f"{{chroot}}/{arg}"
        else:
            return arg

    args = [prefixed(arg) for arg in proc.argv]

    env = {
        **proc.env,
        "PANTS_INTERNAL_ABSOLUTE_PREFIX": "{chroot}/",
    }

    # absolutify coursier cache envvars
    for key in env:
        if key.startswith("COURSIER"):
            env[key] = prefixed(env[key], ".cache")

    request_digest = await Get(
        Digest,
        MergeDigests(
            [
                proc.input_digest,
                *support_digests,
            ]
        ),
    )

    return RunRequest(
        digest=request_digest,
        args=args,
        extra_env=env,
    )


def rules():
    return [*collect_rules(), UnionRule(RunFieldSet, DeployJarFieldSet)]
