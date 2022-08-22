# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from typing import Iterable

from pants.core.goals.package import BuiltPackage
from pants.core.goals.run import RunDebugAdapterRequest, RunFieldSet, RunRequest
from pants.engine.process import Process
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.package.deploy_jar import DeployJarFieldSet
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@rule(level=LogLevel.DEBUG)
async def create_deploy_jar_run_request(
    field_set: DeployJarFieldSet,
) -> RunRequest:

    jdk = await Get(JdkEnvironment, JdkRequest, JdkRequest.from_field(field_set.jdk_version))

    main_class = field_set.main_class.value
    assert main_class is not None

    package = await Get(BuiltPackage, DeployJarFieldSet, field_set)
    assert len(package.artifacts) == 1
    jar_path = package.artifacts[0].relpath
    assert jar_path is not None

    proc = await Get(
        Process,
        JvmProcess(
            jdk=jdk,
            classpath_entries=[f"{{chroot}}/{jar_path}"],
            argv=(main_class,),
            input_digest=package.digest,
            description=f"Run {main_class}.main(String[])",
            use_nailgun=False,
        ),
    )

    # TODO(#16104) This argument re-writing code should use the native {chroot} support.
    # See also `jdk_rules.py` for other argument re-writing code.
    def prefixed(arg: str, prefixes: Iterable[str]) -> str:
        if any(arg.startswith(prefix) for prefix in prefixes):
            return f"{{chroot}}/{arg}"
        else:
            return arg

    prefixes = (jdk.bin_dir, jdk.jdk_preparation_script, jdk.java_home)
    args = [prefixed(arg, prefixes) for arg in proc.argv]

    env = {
        **proc.env,
        "PANTS_INTERNAL_ABSOLUTE_PREFIX": "{chroot}/",
    }

    # absolutify coursier cache envvars
    for key in env:
        if key.startswith("COURSIER"):
            env[key] = prefixed(env[key], (jdk.coursier.cache_dir,))

    return RunRequest(
        digest=proc.input_digest,
        args=args,
        extra_env=env,
        immutable_input_digests=proc.immutable_input_digests,
        append_only_caches=proc.append_only_caches,
    )


@rule
async def run_deploy_jar_debug_adapter_binary(
    field_set: DeployJarFieldSet,
) -> RunDebugAdapterRequest:
    raise NotImplementedError(
        "Debugging a deploy JAR using a debug adapter has not yet been implemented."
    )


def rules():
    return [*collect_rules(), UnionRule(RunFieldSet, DeployJarFieldSet)]
