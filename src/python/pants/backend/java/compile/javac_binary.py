# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass
from typing import ClassVar

from pants.backend.java.compile.javac_subsystem import JavacSubsystem
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.jvm.resolve.coursier_setup import Coursier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JavacBinary:
    digest: Digest
    javac_wrapper_script: ClassVar[str] = "__javac_binary/javac.sh"
    classfiles_relpath: ClassVar[str] = "classfiles"


@rule
async def setup_javac_binary(coursier: Coursier, javac: JavacSubsystem) -> JavacBinary:
    if javac.options.jdk == "system":
        process_result = await Get(
            ProcessResult,
            Process(
                argv=[
                    coursier.coursier.exe,
                    "java",
                    "--system-jvm",
                    "-version",
                ],
                input_digest=coursier.digest,
                description="Invoke Coursier with system-jvm to fingerprint JVM version.",
                cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL,
            ),
        )
        all_output = "\n".join(
            [
                process_result.stderr.decode("utf-8"),
                process_result.stdout.decode("utf-8"),
            ]
        )
        fingerprint_comment_lines = [
            "pants javac script using Coursier --system-jvm.  System java -version:",
            *filter(None, all_output.splitlines()),
        ]
        fingerprint_comment = "".join([f"# {line}\n" for line in fingerprint_comment_lines])
        javac_path_line = (
            f'javac_path="$({coursier.coursier.exe} java-home --system-jvm)/bin/javac"'
        )
    else:
        fingerprint_comment = f"# pants javac script using Coursier with --jvm {javac.options.jdk}"
        javac_path_line = (
            f'javac_path="$({coursier.coursier.exe} java-home --jvm {javac.options.jdk})/bin/javac"'
        )

    # Awkward join so multi-line `fingerprint_comment` won't confuse textwrap.dedent
    javac_wrapper_script = "\n".join(
        [
            fingerprint_comment,
            textwrap.dedent(
                f"""\
                set -eu
                {javac_path_line}
                /bin/mkdir -p {JavacBinary.classfiles_relpath}
                exec "${{javac_path}}" "$@"
                """
            ),
        ]
    )
    javac_wrapper_script_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    JavacBinary.javac_wrapper_script,
                    javac_wrapper_script.encode("utf-8"),
                    is_executable=True,
                ),
            ]
        ),
    )
    return JavacBinary(
        digest=await Get(
            Digest,
            MergeDigests(
                [
                    coursier.digest,
                    javac_wrapper_script_digest,
                ]
            ),
        ),
    )


def rules():
    return [
        *collect_rules(),
    ]
