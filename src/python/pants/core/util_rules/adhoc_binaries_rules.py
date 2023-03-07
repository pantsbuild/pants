# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import sys

from pants.core.util_rules.adhoc_binaries import (  # noqa: PNT20
    GunzipBinary,
    GunzipBinaryRequest,
    PythonBuildStandaloneBinary,
)
from pants.core.util_rules.environments import EnvironmentTarget, LocalEnvironmentTarget
from pants.core.util_rules.system_binaries import SEARCH_PATHS, TarBinary
from pants.engine.fs import DownloadFile
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, FileDigest
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel


@rule(desc="Finding or downloading Python for scripts", level=LogLevel.TRACE)
async def download_python_build_standalone(
    platform: Platform, env_tgt: EnvironmentTarget, tar_binary: TarBinary
) -> PythonBuildStandaloneBinary:
    if isinstance(env_tgt.val, LocalEnvironmentTarget):
        return PythonBuildStandaloneBinary(sys.executable, EMPTY_DIGEST)

    url_plat, fingerprint, bytelen = {
        # No PGO release for aarch64 it seems
        "linux_arm64": (
            "aarch64-unknown-linux-gnu-lto",
            "3d20f40654e4356bd42c4e70ec28f4b8d8dd559884467a4e1745c08729fb740a",
            106653301,
        ),
        "linux_x86_64": (
            "x86_64-unknown-linux-gnu-pgo+lto",
            "c5f7ad956c8870573763ed58b59d7f145830a93378234b815c068c893c0d5c1e",
            42148524,
        ),
        "macos_arm64": (
            "aarch64-apple-darwin-pgo+lto",
            "2508b8d4b725bb45c3e03d2ddd2b8441f1a74677cb6bd6076e692c0923135ded",
            33272226,
        ),
        "macos_x86_64": (
            "x86_64-apple-darwin-pgo+lto",
            "1153b4d3b03cf1e1d8ec93c098160586f665fcc2d162c0812140a716a688df58",
            32847401,
        ),
    }[platform.value]

    python_archive = await Get(
        Digest,
        DownloadFile(
            f"https://github.com/indygreg/python-build-standalone/releases/download/20230116/cpython-3.10.9+20230116-{url_plat}-full.tar.zst",
            FileDigest(
                fingerprint=fingerprint,
                serialized_bytes_length=bytelen,
            ),
        ),
    )

    result = await Get(
        ProcessResult,
        Process(
            argv=[tar_binary.path, "-axvf", f"cpython-3.10.9+20230116-{url_plat}-full.tar.zst"],
            input_digest=python_archive,
            env={"PATH": os.pathsep.join(SEARCH_PATHS)},
            description="Extract Python",
            level=LogLevel.DEBUG,
            output_directories=("python",),
        ),
    )

    return PythonBuildStandaloneBinary("python/install/bin/python3", result.output_digest)


@rule
def find_gunzip(python_binary: PythonBuildStandaloneBinary) -> GunzipBinary:
    return GunzipBinary(python_binary)


@rule
async def find_gunzip_wrapper(_: GunzipBinaryRequest, gunzip: GunzipBinary) -> GunzipBinary:
    return gunzip


def rules():
    return [*collect_rules()]
