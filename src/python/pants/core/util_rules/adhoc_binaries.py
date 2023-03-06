# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
import os
import sys
from textwrap import dedent  # noqa: PNT20

from pants.core.util_rules.environments import EnvironmentTarget, LocalEnvironmentTarget
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.fs import Digest, DownloadFile
from pants.engine.internals.native_engine import FileDigest
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PythonBuildStandaloneBinary:
    """A Python interpreter for use by `@rule` code as an alternative to BashBinary scripts.

    @TODO:...
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
        return FrozenDict(
            {PythonBuildStandaloneBinary.SYMLINK_DIRNAME: self._digest}
        )




@rule(desc="Finding or downloading Python for scripts", level=LogLevel.TRACE)
async def download_python_build_standalone(platform: Platform, env_tgt: EnvironmentTarget) -> PythonBuildStandaloneBinary:
    if isinstance(env_tgt.val, LocalEnvironmentTarget):
        return PythonBuildStandaloneBinary(sys.executable)

    url_plat, fingerprint, bytelen = {
        "linux_arm64": None,
        "linux_x86_64": ("", "44254b934edc8a0d414f256775ee71e192785a6ffb8dd39aa81d9d232f46a741", 47148816),
        "linux_x86_64": ("", "44254b934edc8a0d414f256775ee71e192785a6ffb8dd39aa81d9d232f46a741", 47148816),

        # No PGO release for aarch64 it seems
        "linux_arm64": ("aarch64-unknown-linux-gnu-lto", "3d20f40654e4356bd42c4e70ec28f4b8d8dd559884467a4e1745c08729fb740a", 106653301),
        "linux_x86_64": ("x86_64-unknown-linux-gnu-pgo+lto", "c5f7ad956c8870573763ed58b59d7f145830a93378234b815c068c893c0d5c1e", 42148524),
        "macos_arm64": ("aarch64-apple-darwin-pgo+lto", "2508b8d4b725bb45c3e03d2ddd2b8441f1a74677cb6bd6076e692c0923135ded", 33272226),
        "macos_x86_64": ("x86_64-apple-darwin-pgo+lto", "1153b4d3b03cf1e1d8ec93c098160586f665fcc2d162c0812140a716a688df58", 32847401),

    }[platform]

    python_binary_path = "python/install/bin/python"
    python_build_standalone = await Get(DownloadedExternalTool, ExternalToolRequest(
        DownloadFile(
            f"https://github.com/indygreg/python-build-standalone/releases/download/20230116/cpython-3.10.9+20230116-{url_plat}-full.tar.zst",
            FileDigest(
                fingerprint=fingerprint,
                serialized_bytes_length=bytelen,
            )
        ),
        exe=python_binary_path
    ))
    return PythonBuildStandaloneBinary(
        python_binary_path,
        python_build_standalone.digest
    )

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
    return [*collect_rules()]
