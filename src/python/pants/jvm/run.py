# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import re
from typing import Iterable, Optional, Tuple

from pants.core.goals.run import RunRequest
from pants.core.util_rules.system_binaries import UnzipBinary
from pants.core.util_rules.system_binaries import rules as system_binaries_rules
from pants.engine.addresses import Addresses
from pants.engine.internals.native_engine import Digest, MergeDigests, Snapshot
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import CoarsenedTargets
from pants.jvm.classpath import Classpath
from pants.jvm.classpath import rules as classpath_rules
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.target_types import NO_MAIN_CLASS, GenericJvmRunRequest
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


async def _find_main(
    unzip: UnzipBinary, jdk: JdkEnvironment, input_digest: Digest, jarfile: str
) -> str:
    # Find the `main` method, first by inspecting the manifest, and then by inspecting the index
    # of the included classes.

    main_from_manifest = await _find_main_by_manifest(unzip, input_digest, jarfile)

    if main_from_manifest:
        return main_from_manifest

    mains_from_javap = await _find_main_by_javap(unzip, jdk, input_digest, jarfile)

    if len(mains_from_javap) == 0:
        raise Exception(
            f"Could not find a `public static void main(String[])` method in `{jarfile}`"
        )
    if len(mains_from_javap) > 1:
        raise Exception(f"Found multiple classes that provide `main` methods in `{jarfile}`.")

    return mains_from_javap[0]


async def _find_main_by_manifest(
    unzip: UnzipBinary, input_digest: Digest, jarfile: str
) -> Optional[str]:
    # jvm only allows `-cp` or `-jar` to be specified, and `-jar` takes precedence. So, even for a
    # JAR with a valid `Main-Class` in the manifest, we need to peek inside the manifest and
    # extract `main` ourself.
    manifest = await Get(
        FallibleProcessResult,
        Process(
            description="Get manifest destails from classpath",
            argv=(unzip.path, "-p", jarfile, "META-INF/MANIFEST.MF"),
            input_digest=input_digest,
        ),
    )

    if manifest.exit_code == 11:
        # No manifest file present (occurs with e.g. first-party Java sources)
        return None

    main_class_lines = [
        r.strip()
        for _, is_main, r in (
            i.partition("Main-Class:") for i in manifest.stdout.decode().splitlines()
        )
        if is_main
    ]

    if not main_class_lines:
        return None
    if main_class_lines[0] == NO_MAIN_CLASS:
        return None
    return main_class_lines[0]


async def _find_main_by_javap(
    unzip: UnzipBinary, jdk: JdkEnvironment, input_digest: Digest, jarfile: str
) -> Tuple[str, ...]:
    # Finds the `main` class by inspecting all of the classes inside the specified JAR
    # to find one with a JVM main method.

    first_jar_contents = await Get(
        ProcessResult,
        Process(
            description=f"Get class files from `{jarfile}` to find `main`",
            argv=(unzip.path, jarfile, "*.class", "-d", "zip_output"),
            input_digest=input_digest,
            output_directories=("zip_output",),
        ),
    )

    outputs = await Get(Snapshot, Digest, first_jar_contents.output_digest)

    class_index = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            classpath_entries=[f"{jdk.java_home}/lib/tools.jar"],
            argv=[
                "com.sun.tools.javap.Main",
                *("-cp", jarfile),
                *outputs.files,
            ],
            input_digest=first_jar_contents.output_digest,
            description=f"Index class files in `{jarfile}` to find `main`",
            level=LogLevel.DEBUG,
        ),
    )

    output = class_index.stdout.decode()
    p = re.compile(r"^public .*?class (.*?) .*?{(.*?)}$", flags=re.MULTILINE | re.DOTALL)
    classes: list[tuple[str, str]] = re.findall(p, output)
    mains = tuple(
        classname
        for classname, definition in classes
        if "public static void main(java.lang.String[])" in definition
    )

    return mains


@rule
async def create_run_request(
    request: GenericJvmRunRequest,
    unzip: UnzipBinary,
) -> RunRequest:
    field_set = request.field_set

    jdk = await Get(JdkEnvironment, JdkRequest, JdkRequest.from_field(field_set.jdk_version))

    artifacts = await Get(CoarsenedTargets, Addresses([field_set.address]))
    classpath = await Get(Classpath, CoarsenedTargets, artifacts)

    classpath_entries = list(classpath.args(prefix="{chroot}"))

    input_digest = await Get(Digest, MergeDigests(classpath.digests()))

    # Assume that the first entry in `classpath_entries` is the artifact specified in `Addresses`?
    main_class = field_set.main_class.value
    if main_class is None:
        main_class = await _find_main(unzip, jdk, input_digest, classpath_entries[0])

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

    return _post_process_jvm_process(proc, jdk)


def _post_process_jvm_process(proc: Process, jdk: JdkEnvironment) -> RunRequest:
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
        *system_binaries_rules(),
        *jdk_rules(),
        *classpath_rules(),
    ]
