# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import shlex
import textwrap
from dataclasses import dataclass
from typing import ClassVar, Iterable

from pants.backend.java.compile.javac_subsystem import JavacSubsystem
from pants.engine.fs import CreateDigest, Digest, FileContent, FileDigest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.process import BashBinary, FallibleProcessResult, Process, ProcessCacheScope
from pants.engine.rules import collect_rules, rule
from pants.jvm.compile import ClasspathEntry
from pants.jvm.resolve.coursier_fetch import Coordinate, Coordinates, CoursierLockfileEntry
from pants.jvm.resolve.coursier_setup import Coursier
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class JdkSetup:
    digest: Digest
    nailgun_jar: str
    coursier: Coursier
    jdk_preparation_script: ClassVar[str] = "__jdk.sh"
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


@rule
async def setup_jdk(coursier: Coursier, javac: JavacSubsystem, bash: BashBinary) -> JdkSetup:
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

    if javac.options.jdk == "system":
        coursier_jdk_option = "--system-jvm"
    else:
        coursier_jdk_option = shlex.quote(f"--jvm={javac.options.jdk}")
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
            input_digest=coursier.digest,
            append_only_caches=coursier.append_only_caches,
            env=coursier.env,
            description=f"Ensure download of JDK {coursier_jdk_option}.",
            cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL,
            level=LogLevel.DEBUG,
        ),
    )

    if java_version_result.exit_code != 0:
        raise ValueError(
            f"Failed to locate Java for JDK `{javac.options.jdk}`:\n"
            f"{java_version_result.stderr.decode('utf-8')}"
        )

    java_version = java_version_result.stdout.decode("utf-8").strip()

    # TODO: Locate `ln`.
    jdk_preparation_script = textwrap.dedent(
        f"""\
        # pants javac script using Coursier {coursier_jdk_option}. `java -version`: {java_version}"
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
                    JdkSetup.jdk_preparation_script,
                    jdk_preparation_script.encode("utf-8"),
                    is_executable=True,
                ),
            ]
        ),
    )
    return JdkSetup(
        digest=await Get(
            Digest,
            MergeDigests(
                [
                    coursier.digest,
                    jdk_preparation_script_digest,
                    nailgun.digest,
                ]
            ),
        ),
        nailgun_jar=nailgun.filenames[0],
        coursier=coursier,
    )


def rules():
    return collect_rules()
