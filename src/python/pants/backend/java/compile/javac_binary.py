# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass
from typing import ClassVar

from pants.backend.java.compile.javac_subsystem import JavacSubsystem
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.rules import Get, collect_rules, rule
from pants.jvm.resolve.coursier_setup import Coursier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JavacBinary:
    digest: Digest
    javac: ClassVar[str] = "__javac_binary/javac.sh"
    classfiles_relpath: ClassVar[str] = "classfiles"


@rule
async def setup_javac_binary(coursier: Coursier, javac: JavacSubsystem) -> JavacBinary:
    javac_wrapper_script = textwrap.dedent(
        f"""\
        set -eux
        /bin/echo "COURSIER FILE: $(/usr/bin/file {coursier.coursier.exe})"
        javac_path="$({coursier.coursier.exe} java-home --jvm {javac.options.jdk})/bin/javac"
        /bin/echo "javac_path: ${{javac_path}}"
        /bin/echo "JAVAC FILE: $(/usr/bin/file ${{javac_path}})"
        /bin/echo "ARCH: $(/usr/bin/arch)"
        /bin/mkdir -p {JavacBinary.classfiles_relpath}
        exec "${{javac_path}}" "$@"
        """
    )

    print("WRAPPER SCRIPT:")
    print(javac_wrapper_script)
    javac_wrapper_script_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    JavacBinary.javac,
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
