# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

import pkg_resources

from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE, GenerateToolLockfileSentinel
from pants.engine.fs import AddPrefix, CreateDigest, Digest, Directory, FileContent
from pants.engine.internals.native_engine import MergeDigests, RemovePrefix
from pants.engine.process import FallibleProcessResult, ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, GenerateJvmToolLockfileSentinel
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

_STRIP_JAR_BASENAME = "StripJar.java"
_OUTPUT_PATH = "__stripped_jars"


class StripJarToolLockfileSentinel(GenerateJvmToolLockfileSentinel):
    resolve_name = "strip-jar"


@dataclass(frozen=True)
class StripJarRequest:
    digest: Digest
    filenames: Tuple[str, ...]


@dataclass(frozen=True)
class FallibleStripJarResult:
    process_result: FallibleProcessResult


@dataclass(frozen=True)
class StripJarCompiledClassfiles:
    digest: Digest


@rule(level=LogLevel.DEBUG)
async def strip_jar(
    processor_classfiles: StripJarCompiledClassfiles,
    jdk: InternalJdk,
    request: StripJarRequest,
) -> Digest:
    filenames = list(request.filenames)

    if len(filenames) == 0:
        return request.digest

    input_path = "__jars_to_strip"
    toolcp_relpath = "__toolcp"
    processorcp_relpath = "__processorcp"

    lockfile_request = await Get(GenerateJvmLockfileFromTool, StripJarToolLockfileSentinel())

    tool_classpath, prefixed_jars_digest = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(lockfile=lockfile_request),
        ),
        Get(Digest, AddPrefix(request.digest, input_path)),
    )

    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
        processorcp_relpath: processor_classfiles.digest,
    }

    process_result = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            classpath_entries=[
                *tool_classpath.classpath_entries(toolcp_relpath),
                processorcp_relpath,
            ],
            argv=["org.pantsbuild.stripjar.StripJar", input_path, _OUTPUT_PATH, *filenames],
            input_digest=prefixed_jars_digest,
            extra_immutable_input_digests=extra_immutable_input_digests,
            output_directories=(_OUTPUT_PATH,),
            extra_nailgun_keys=extra_immutable_input_digests,
            description=f"Stripping jar {filenames[0]}",
            level=LogLevel.DEBUG,
            cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL,
        ),
    )

    return await Get(Digest, RemovePrefix(process_result.output_digest, _OUTPUT_PATH))


def _load_strip_jar_source() -> bytes:
    return pkg_resources.resource_string(__name__, _STRIP_JAR_BASENAME)


# TODO(13879): Consolidate compilation of wrapper binaries to common rules.
@rule
async def build_processors(jdk: InternalJdk) -> StripJarCompiledClassfiles:
    dest_dir = "classfiles"
    lockfile_request = await Get(GenerateJvmLockfileFromTool, StripJarToolLockfileSentinel())
    materialized_classpath, source_digest = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(prefix="__toolcp", lockfile=lockfile_request),
        ),
        Get(
            Digest,
            CreateDigest(
                [
                    FileContent(
                        path=_STRIP_JAR_BASENAME,
                        content=_load_strip_jar_source(),
                    ),
                    Directory(dest_dir),
                ]
            ),
        ),
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                materialized_classpath.digest,
                source_digest,
            )
        ),
    )

    process_result = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            classpath_entries=[f"{jdk.java_home}/lib/tools.jar"],
            argv=[
                "com.sun.tools.javac.Main",
                "-cp",
                ":".join(materialized_classpath.classpath_entries()),
                "-d",
                dest_dir,
                _STRIP_JAR_BASENAME,
            ],
            input_digest=merged_digest,
            output_directories=(dest_dir,),
            description=f"Compile {_STRIP_JAR_BASENAME} with javac",
            level=LogLevel.DEBUG,
            # NB: We do not use nailgun for this process, since it is launched exactly once.
            use_nailgun=False,
        ),
    )
    stripped_classfiles_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, dest_dir)
    )
    return StripJarCompiledClassfiles(digest=stripped_classfiles_digest)


@rule
def generate_strip_jar_lockfile_request(
    _: StripJarToolLockfileSentinel,
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool(
        artifact_inputs=FrozenOrderedSet(
            {
                "io.github.zlika:reproducible-build-maven-plugin:0.16",
            }
        ),
        artifact_option_name="n/a",
        lockfile_option_name="n/a",
        resolve_name=StripJarToolLockfileSentinel.resolve_name,
        read_lockfile_dest=DEFAULT_TOOL_LOCKFILE,
        write_lockfile_dest="src/python/pants/jvm/strip_jar/strip_jar.lock",
        default_lockfile_resource=(
            "pants.jvm.strip_jar",
            "strip_jar.lock",
        ),
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateToolLockfileSentinel, StripJarToolLockfileSentinel),
    ]
