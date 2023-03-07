# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from textwrap import dedent  # noqa: PNT20

from pants.core.util_rules.environments import EnvironmentTarget, LocalEnvironmentTarget
from pants.core.util_rules.system_binaries import SEARCH_PATHS, TarBinary
from pants.engine.fs import DownloadFile
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, FileDigest
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PythonBuildStandaloneBinary:
    """A Python interpreter for use by `@rule` code as an alternative to BashBinary scripts.

    This interpreter is provided by Python Build Standalone https://gregoryszorc.com/docs/python-build-standalone/main/,
    which has a few caveats. Namely it doesn't play nicely with third-party sdists. Meaning Pants'
    scripts being run by PythonBuildStandalone should avoid third-party sdists.
    """

    SYMLINK_DIRNAME = ".python-build-standalone"

    _path: str
    """The path to the Python binary inside the immutable input symlink."""
    _digest: Digest

    @property
    def path(self) -> str:
        return f"{PythonBuildStandaloneBinary.SYMLINK_DIRNAME}/{self._path}"

    @property
    def immutable_input_digests(self) -> FrozenDict[str, Digest]:
        return FrozenDict({PythonBuildStandaloneBinary.SYMLINK_DIRNAME: self._digest})


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
            "c811df664ca233815f7b4bfec4648192b74599e2639554ba634d8891bb60a0ca",
            154120974,
        ),
        "linux_x86_64": (
            "x86_64-unknown-linux-gnu-pgo+lto",
            "9cbad5f74dc958f65e7d0c3d159ba3ff5e1cab94b861d3f6e281c8a64fbbca48",
            81272463,
        ),
        "macos_arm64": (
            "aarch64-apple-darwin-pgo+lto",
            "603af4d150bf3158961684e00104e273c0aab419b142760ff542aeee8bde32f9",
            66451944,
        ),
        "macos_x86_64": (
            "x86_64-apple-darwin-pgo+lto",
            "5b4d4d425414cd4a8750b544ab05d284e5acd837d83f1c661320b8aea3762393",
            65449500,
        ),
    }[platform.value]

    filename = f"cpython-3.10.9+20230116-{url_plat}-full.tar.gz"
    python_archive = await Get(
        Digest,
        DownloadFile(
            f"https://github.com/thejcannon/python-build-standalone/releases/download/20230116/{filename}",
            FileDigest(
                fingerprint=fingerprint,
                serialized_bytes_length=bytelen,
            ),
        ),
    )

    result = await Get(
        ProcessResult,
        Process(
            argv=[tar_binary.path, "-axvf", filename],
            input_digest=python_archive,
            env={"PATH": os.pathsep.join(SEARCH_PATHS)},
            description="Extract Python",
            level=LogLevel.DEBUG,
            output_directories=("python",),
        ),
    )

    return PythonBuildStandaloneBinary("python/install/bin/python3", result.output_digest)


@dataclass(frozen=True)
class GunzipBinaryRequest:
    pass


@dataclass(frozen=True)
class GunzipBinary:
    python_binary: PythonBuildStandaloneBinary

    def extract_archive_argv(self, archive_path: str, extract_path: str) -> tuple[str, ...]:
        archive_name = os.path.basename(archive_path)
        dest_file_name = os.path.splitext(archive_name)[0]
        dest_path = os.path.join(extract_path, dest_file_name)
        script = dedent(
            f"""
            import gzip
            import shutil
            with gzip.GzipFile(filename={archive_path!r}, mode="rb") as source:
                with open({dest_path!r}, "wb") as dest:
                    shutil.copyfileobj(source, dest)
            """
        )
        return (self.python_binary.path, "-c", script)


@rule
def find_gunzip(python_binary: PythonBuildStandaloneBinary) -> GunzipBinary:
    return GunzipBinary(python_binary)


@rule
async def find_gunzip_wrapper(_: GunzipBinaryRequest, gunzip: GunzipBinary) -> GunzipBinary:
    return gunzip


def rules():
    return collect_rules()
