# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass
from typing import ClassVar

from pants.backend.java.util_rules import JdkSetup
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.rules import Get, collect_rules, rule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JavacBinary:
    digest: Digest
    javac_wrapper_script: ClassVar[str] = "__javac_binary/javac.sh"
    classfiles_relpath: ClassVar[str] = "classfiles"


@rule
async def setup_javac_binary(jdk_setup: JdkSetup) -> JavacBinary:
    # Awkward join so multi-line `fingerprint_comment` won't confuse textwrap.dedent
    javac_wrapper_script = "\n".join(
        [
            jdk_setup.fingerprint_comment,
            textwrap.dedent(
                f"""\
                set -eu
                /bin/mkdir -p {JavacBinary.classfiles_relpath}
                exec $({' '.join(jdk_setup.java_home_cmd)})/bin/javac "$@"
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
                    jdk_setup.digest,
                    javac_wrapper_script_digest,
                ]
            ),
        ),
    )


def rules():
    return [
        *collect_rules(),
    ]
