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
    if env_tgt.val is None or isinstance(env_tgt.val, LocalEnvironmentTarget):
        return PythonBuildStandaloneBinary(sys.executable, EMPTY_DIGEST)

    url_plat, fingerprint, bytelen = {
        "linux_arm64": (
            "aarch64-unknown-linux-gnu",
            "1ba520c0db431c84305677f56eb9a4254f5097430ed443e92fc8617f8fba973d",
            23873387,
        ),
        "linux_x86_64": (
            "x86_64-unknown-linux-gnu",
            "7ba397787932393e65fc2fb9fcfabf54f2bb6751d5da2b45913cb25b2d493758",
            26129729,
        ),
        "macos_arm64": (
            "aarch64-apple-darwin",
            "d732d212d42315ac27c6da3e0b69636737a8d72086c980daf844344c010cab80",
            17084463,
        ),
        "macos_x86_64": (
            "x86_64-apple-darwin",
            "3948384af5e8d4ee7e5ccc648322b99c1c5cf4979954ed5e6b3382c69d6db71e",
            17059474,
        ),
    }[platform.value]

    # NB: This should match the maximum version supported by the Pants package
    filename = f"cpython-3.9.16+20230116-{url_plat}-install_only.tar.gz"
    python_archive = await Get(
        Digest,
        DownloadFile(
            f"https://github.com/indygreg/python-build-standalone/releases/download/20230116/{filename}",
            FileDigest(
                fingerprint=fingerprint,
                serialized_bytes_length=bytelen,
            ),
        ),
    )

    result = await Get(
        ProcessResult,
        Process(
            argv=[tar_binary.path, "-xvf", filename],
            input_digest=python_archive,
            env={"PATH": os.pathsep.join(SEARCH_PATHS)},
            description="Extract Python",
            level=LogLevel.DEBUG,
            output_directories=("python",),
        ),
    )

    return PythonBuildStandaloneBinary("python/bin/python3", result.output_digest)


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
