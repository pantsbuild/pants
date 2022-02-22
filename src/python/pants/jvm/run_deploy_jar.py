# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import logging
from dataclasses import dataclass
from typing import Iterable

from pants.core.goals.package import BuiltPackage
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.engine.fs import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.internals.native_engine import AddPrefix
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.package.deploy_jar import DeployJarFieldSet
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class __RuntimeJvm:
    """Allows Coursier to download a JDK into a Digest, rather than an append-only cache for use
    with `pants run`.

    This is a hideous stop-gap, which will no longer be necessary once `InteractiveProcess` supports
    append-only caches. (See #13852 for details on how to do this.)
    """

    digest: Digest


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

    support_digests = await MultiGet(
        Get(Digest, AddPrefix(digest, prefix))
        for prefix, digest in proc.immutable_input_digests.items()
    )

    runtime_jvm = await Get(__RuntimeJvm, JdkEnvironment, jdk)
    support_digests += (runtime_jvm.digest,)

    # TODO(#14386) This argument re-writing code should be done in a more standardised way.
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


@rule
async def ensure_jdk_for_pants_run(jdk: JdkEnvironment) -> __RuntimeJvm:
    # `tools.jar` is distributed with the JDK, so we can rely on it existing.
    ensure_jvm_process = await Get(
        Process,
        JvmProcess(
            jdk=jdk,
            classpath_entries=[f"{jdk.java_home}/lib/tools.jar"],
            argv=["com.sun.tools.javac.Main", "--version"],
            input_digest=EMPTY_DIGEST,
            description="Ensure download of JDK for `pants run` use",
        ),
    )

    # Do not treat the coursier JDK locations as an append-only cache, so that we can capture the
    # downloaded JDK in a `Digest`

    ensure_jvm_process = dataclasses.replace(
        ensure_jvm_process,
        append_only_caches=FrozenDict(),
        output_directories=(".cache/jdk", ".cache/arc"),
        use_nailgun=(),
    )

    ensure_jvm = await Get(ProcessResult, Process, ensure_jvm_process)

    return __RuntimeJvm(ensure_jvm.output_digest)


def rules():
    return [*collect_rules(), UnionRule(RunFieldSet, DeployJarFieldSet)]
