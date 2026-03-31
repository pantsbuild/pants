# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from pants.core.goals.run import RunRequest
from pants.core.util_rules.system_binaries import UnzipBinary
from pants.core.util_rules.system_binaries import rules as system_binaries_rules
from pants.engine.addresses import Addresses
from pants.engine.internals.graph import resolve_coarsened_targets
from pants.engine.internals.native_engine import Digest, MergeDigests, UnionRule
from pants.engine.intrinsics import digest_to_snapshot, execute_process, merge_digests
from pants.engine.process import Process, execute_process_or_raise
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.jvm.classpath import classpath as classpath_get
from pants.jvm.classpath import rules as classpath_rules
from pants.jvm.jdk_rules import (
    JdkEnvironment,
    JdkRequest,
    JvmProcess,
    jvm_process,
    prepare_jdk_environment,
)
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.target_types import (
    NO_MAIN_CLASS,
    GenericJvmRunRequest,
    JvmArtifactFieldSet,
    JvmRunnableSourceFieldSet,
)
from pants.util.logging import LogLevel
from pants.util.memo import memoized

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
) -> str | None:
    # jvm only allows `-cp` or `-jar` to be specified, and `-jar` takes precedence. So, even for a
    # JAR with a valid `Main-Class` in the manifest, we need to peek inside the manifest and
    # extract `main` ourself.
    manifest = await execute_process(
        Process(
            description="Get manifest destails from classpath",
            argv=(unzip.path, "-p", jarfile, "META-INF/MANIFEST.MF"),
            input_digest=input_digest,
        ),
        **implicitly(),
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
) -> tuple[str, ...]:
    # Finds the `main` class by inspecting all of the classes inside the specified JAR
    # to find one with a JVM main method.

    first_jar_contents = await execute_process_or_raise(
        **implicitly(
            Process(
                description=f"Get class files from `{jarfile}` to find `main`",
                argv=(unzip.path, jarfile, "*.class", "-d", "zip_output"),
                input_digest=input_digest,
                output_directories=("zip_output",),
            )
        )
    )

    outputs = await digest_to_snapshot(first_jar_contents.output_digest)

    class_index = await execute_process_or_raise(
        **implicitly(
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
            )
        )
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

    jdk = await prepare_jdk_environment(**implicitly(JdkRequest.from_field(field_set.jdk_version)))

    artifacts = await resolve_coarsened_targets(**implicitly(Addresses([field_set.address])))
    classpath = await classpath_get(artifacts, **implicitly())

    classpath_entries = list(classpath.args(prefix="{chroot}"))

    input_digest = await merge_digests(MergeDigests(classpath.digests()))

    # Assume that the first entry in `classpath_entries` is the artifact specified in `Addresses`?
    main_class = field_set.main_class.value
    if main_class is None:
        main_class = await _find_main(unzip, jdk, input_digest, classpath_entries[0])

    proc = await jvm_process(
        **implicitly(
            JvmProcess(
                jdk=jdk,
                classpath_entries=classpath_entries,
                argv=(main_class,),
                input_digest=input_digest,
                description=f"Run {field_set.address}",
                use_nailgun=False,
            )
        )
    )

    return _post_process_jvm_process(proc, jdk)


@memoized
def _jvm_source_run_request_rule(cls: type[JvmRunnableSourceFieldSet]) -> Iterable[Rule]:
    @rule(
        canonical_name_suffix=cls.__name__,
        _param_type_overrides={"request": cls},
        level=LogLevel.DEBUG,
    )
    async def jvm_source_run_request(request: JvmRunnableSourceFieldSet) -> RunRequest:
        return await create_run_request(GenericJvmRunRequest(request), **implicitly())

    return [*run_rules(), *collect_rules(locals())]


def jvm_run_rules(cls: type[JvmRunnableSourceFieldSet]) -> Iterable[Rule | UnionRule]:
    yield from _jvm_source_run_request_rule(cls)
    yield from cls.rules()


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


def run_rules():
    return [
        *collect_rules(),
        *system_binaries_rules(),
        *jdk_rules(),
        *classpath_rules(),
    ]


def rules():
    return [
        *run_rules(),
        *jvm_run_rules(JvmArtifactFieldSet),
    ]
