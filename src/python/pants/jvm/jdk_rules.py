# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os
import re
import shlex
import textwrap
from dataclasses import dataclass
from typing import ClassVar, Iterable

from pants.engine.fs import CreateDigest, Digest, FileContent, FileDigest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import BashBinary, FallibleProcessResult, Process, ProcessCacheScope
from pants.engine.rules import collect_rules, rule
from pants.jvm.compile import ClasspathEntry
from pants.jvm.resolve.common import Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry
from pants.jvm.resolve.coursier_setup import Coursier
from pants.jvm.subsystems import JvmSubsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class JdkSetup:
    _digest: Digest
    nailgun_jar: str
    coursier: Coursier
    jre_major_version: int

    bin_dir: ClassVar[str] = "__jdk"
    jdk_preparation_script: ClassVar[str] = f"{bin_dir}/jdk.sh"
    java_home: ClassVar[str] = "__java_home"

    def args(self, bash: BashBinary, classpath_entries: Iterable[str]) -> tuple[str, ...]:
        return (
            bash.path,
            self.jdk_preparation_script,
            f"{self.java_home}/bin/java",
            "-cp",
            ":".join([self.nailgun_jar, *classpath_entries]),
        )

    @property
    def env(self) -> dict[str, str]:
        return self.coursier.env

    @property
    def append_only_caches(self) -> dict[str, str]:
        return self.coursier.append_only_caches

    @property
    def immutable_input_digests(self) -> dict[str, Digest]:
        return {**self.coursier.immutable_input_digests, self.bin_dir: self._digest}


VERSION_REGEX = re.compile(r"version \"(.+?)\"")


def parse_jre_major_version(version_lines: str) -> int | None:
    for line in version_lines.splitlines():
        m = VERSION_REGEX.search(line)
        if m:
            major_version, _, _ = m[1].partition(".")
            return int(major_version)
    return None


@rule
async def setup_jdk(coursier: Coursier, jvm: JvmSubsystem, bash: BashBinary) -> JdkSetup:
    nailgun = await Get(
        ClasspathEntry,
        CoursierLockfileEntry(
            coord=Coordinate.from_coord_str("com.martiansoftware:nailgun-server:0.9.1"),
            file_name="com.martiansoftware_nailgun-server_0.9.1.jar",
            direct_dependencies=Coordinates(),
            dependencies=Coordinates(),
            file_digest=FileDigest(
                fingerprint="4518faa6bf4bd26fccdc4d85e1625dc679381a08d56872d8ad12151dda9cef25",
                serialized_bytes_length=32927,
            ),
        ),
    )

    if jvm.jdk == "system":
        coursier_jdk_option = "--system-jvm"
    else:
        coursier_jdk_option = shlex.quote(f"--jvm={jvm.jdk}")
    # NB: We `set +e` in the subshell to ensure that it exits as well.
    #  see https://unix.stackexchange.com/a/23099
    java_home_command = " ".join(("set +e;", *coursier.args(["java-home", coursier_jdk_option])))

    java_version_result = await Get(
        FallibleProcessResult,
        Process(
            argv=(
                bash.path,
                "-c",
                f"$({java_home_command})/bin/java -version",
            ),
            append_only_caches=coursier.append_only_caches,
            immutable_input_digests=coursier.immutable_input_digests,
            env=coursier.env,
            description=f"Ensure download of JDK {coursier_jdk_option}.",
            cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL,
            level=LogLevel.DEBUG,
        ),
    )

    if java_version_result.exit_code != 0:
        raise ValueError(
            f"Failed to locate Java for JDK `{jvm.jdk}`:\n"
            f"{java_version_result.stderr.decode('utf-8')}"
        )

    java_version = java_version_result.stderr.decode("utf-8").strip()
    jre_major_version = parse_jre_major_version(java_version)
    if not jre_major_version:
        raise ValueError(
            f"Pants was unable to parse the output of `java -version` for JDK `{jvm.jdk}`. "
            "Please open an issue at https://github.com/pantsbuild/pants/issues/new/choose "
            f"with the following output:\n\n{java_version}"
        )

    # TODO: Locate `ln`.
    version_comment = "\n".join(f"# {line}" for line in java_version.splitlines())
    jdk_preparation_script = textwrap.dedent(
        f"""\
        # pants javac script using Coursier {coursier_jdk_option}. `java -version`:"
        {version_comment}
        set -eu

        /bin/ln -s "$({java_home_command})" "{JdkSetup.java_home}"
        exec "$@"
        """
    )
    jdk_preparation_script_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    os.path.basename(JdkSetup.jdk_preparation_script),
                    jdk_preparation_script.encode("utf-8"),
                    is_executable=True,
                ),
            ]
        ),
    )
    return JdkSetup(
        _digest=await Get(
            Digest,
            MergeDigests(
                [
                    jdk_preparation_script_digest,
                    nailgun.digest,
                ]
            ),
        ),
        nailgun_jar=os.path.join(JdkSetup.bin_dir, nailgun.filenames[0]),
        coursier=coursier,
        jre_major_version=jre_major_version,
    )


"""
        return Process(
            [
                *jdk_setup.args(bash, tool_classpath.classpath_entries(toolcp_relpath)),
                "org.apache.avro.tool.Main",
                *args,
            ],
            input_digest=overridden_input_digest
            if overridden_input_digest is not None
            else input_digest,
            immutable_input_digests=immutable_input_digests,
            use_nailgun=immutable_input_digests,
            description="Generating Java sources from Avro source.",
            level=LogLevel.DEBUG,
            output_directories=(overridden_output_dir if overridden_output_dir else output_dir,),
            env=jdk_setup.env,
            append_only_caches=jdk_setup.append_only_caches,
        )
"""


@frozen_after_init
@dataclass(unsafe_hash=True)
class JvmProcess:
    args: tuple[str, ...]
    classpath_entries: tuple[str, ...]
    input_digest: Digest
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    use_nailgun: tuple[str, ...]
    output_files: tuple[str, ...]
    output_directories: tuple[str, ...]
    timeout_seconds: int | float | None
    platform: Platform | None
    extra_immutable_input_digests: FrozenDict[str, Digest]
    extra_env: FrozenDict[str, str]

    def __init__(
        self,
        args: Iterable[str],
        classpath_entries: Iterable[str],
        input_digest: Digest,
        description: str,
        level: LogLevel,
        use_nailgun: Iterable[str] | None = None,
        output_files: Iterable[str] | None = None,
        output_directories: Iterable[str] | None = None,
        extra_immutable_input_digests: dict[str, Digest] | None = None,
        extra_env: dict[str, str] | None = None,
        timeout_seconds: int | float | None = None,
        platform: Platform | None = None,
    ):

        self.args = tuple(args)
        self.classpath_entries = tuple(classpath_entries)
        self.input_digest = input_digest
        self.description = description
        self.level = level
        self.use_nailgun = tuple(use_nailgun or ())
        self.output_files = tuple(output_files or ())
        self.output_directories = tuple(output_directories or ())
        self.timeout_seconds = timeout_seconds
        self.platform = platform

        self.extra_immutable_input_digests = FrozenDict(extra_immutable_input_digests or {})
        self.extra_env = FrozenDict(extra_env or {})


@rule
async def jvm_process(bash: BashBinary, jdk_setup: JdkSetup, request: JvmProcess) -> Process:

    immutable_input_digests = {
        **jdk_setup.immutable_input_digests,
        **request.extra_immutable_input_digests,
    }
    env = {**jdk_setup.env, **request.extra_env}

    return Process(
        [*jdk_setup.args(bash, request.classpath_entries), *request.args],
        input_digest=request.input_digest,
        immutable_input_digests=immutable_input_digests,
        use_nailgun=request.use_nailgun,
        description=request.description,
        level=request.level,
        output_directories=request.output_directories,
        env=env,
        platform=request.platform,
        timeout_seconds=request.timeout_seconds,
        append_only_caches=jdk_setup.append_only_caches,
        output_files=request.output_files,
    )


def rules():
    return collect_rules()
