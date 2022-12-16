# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from typing import Iterable

from pants.core.goals.package import BuiltPackage
from pants.core.goals.run import RunRequest
from pants.core.util_rules.system_binaries import UnzipBinary
from pants.engine.addresses import Addresses
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import CoarsenedTargets
from pants.jvm.classpath import Classpath
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.package.deploy_jar import DeployJarFieldSet
from pants.jvm.target_types import JvmArtifactFieldSet
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


@rule(level=LogLevel.DEBUG)
async def create_jvm_artifact_run_request(
    field_set: JvmArtifactFieldSet,
    unzip: UnzipBinary,
) -> RunRequest:

    jdk = await Get(JdkEnvironment, JdkRequest, JdkRequest.from_field(field_set.jdk_version))

    artifacts = await Get(CoarsenedTargets, Addresses([field_set.address]))
    classpath = await Get(Classpath, CoarsenedTargets, artifacts)

    classpath_entries = list(classpath.args(prefix="{chroot}"))

    input_digest = await Get(Digest, MergeDigests(classpath.digests()))

    # Assume that the first entry is the artifact specified in `Addresses`?

    # jvm only allows `-cp` or `-jar` to be specified, and `-jar` takes precedence. So, we need
    # peek inside the JAR for the thing we want to run, and extract its `Main-Class` line from the
    # manifest.
    manifest = await Get(
        ProcessResult,
        Process(
            description="Get manifest destails from classpath",
            argv=(unzip.path, "-p", classpath_entries[0], "META-INF/MANIFEST.MF"),
            input_digest=input_digest,
        ),
    )

    main_class_line = [
        r.strip()
        for _, is_main, r in (
            i.partition("Main-Class:") for i in manifest.stdout.decode().splitlines()
        )
        if is_main
    ]
    assert main_class_line
    main_class = main_class_line[0]

    proc = await Get(
        Process,
        JvmProcess(
            jdk=jdk,
            classpath_entries=classpath_entries,
            argv=(main_class,),
            input_digest=input_digest,
            description=f"Run {field_set.address}",
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


def rules():
    return [
        *collect_rules(),
        *DeployJarFieldSet.rules(),
        *JvmArtifactFieldSet.rules(),
    ]
