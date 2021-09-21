# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.java.compile.javac_subsystem import JavacSubsystem
from pants.engine.fs import Digest
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.jvm.resolve.coursier_setup import Coursier


@dataclass(frozen=True)
class JdkSetup:
    java_home: str
    fingerprint_comment: str


@rule
async def setup_jdk(coursier: Coursier, javac: JavacSubsystem) -> JdkSetup:
    if javac.options.jdk == "system":
        coursier_jdk_option = "--system-jvm"
    else:
        coursier_jdk_option = f"--jvm={javac.options.jdk}"

    java_home_result = await Get(
        FallibleProcessResult,
        Process(
            argv=(
                coursier.coursier.exe,
                "java-home",
                coursier_jdk_option,
            ),
            input_digest=coursier.digest,
            description=f"Ensure download of JDK {coursier_jdk_option}.",
        ),
    )

    if java_home_result.exit_code != 0:
        raise ValueError(
            f"Failed to determine JAVA_HOME for JDK {javac.options.jdk}: {java_home_result.stderr.decode('utf-8')}"
        )

    java_home = java_home_result.stdout.decode("utf-8").strip()

    version_result = await Get(
        ProcessResult,
        Process(
            argv=(
                f"{java_home}/bin/java",
                "-version",
            ),
            description=f"Extract version from JDK {coursier_jdk_option}.",
        ),
    )

    all_output = "\n".join(
        [
            version_result.stderr.decode("utf-8"),
            version_result.stdout.decode("utf-8"),
        ]
    )
    fingerprint_comment_lines = [
        f"pants javac script using Coursier {coursier_jdk_option}.  `java -version`:",
        *filter(None, all_output.splitlines()),
    ]
    fingerprint_comment = "".join([f"# {line}\n" for line in fingerprint_comment_lines])

    return JdkSetup(
        java_home=java_home,
        fingerprint_comment=fingerprint_comment,
    )


def rules():
    return collect_rules()
