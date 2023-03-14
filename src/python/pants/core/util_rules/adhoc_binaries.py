# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from textwrap import dedent  # noqa: PNT20

from pants.core.subsystems.python_bootstrap import PythonBootstrapSubsystem  # noqa: PNT20
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
    scripts being run by Python Build Standalone should avoid third-party sdists.
    """

    SYMLINK_DIRNAME = ".python-build-standalone"

    path: str
    _digest: Digest

    @property
    def immutable_input_digests(self) -> FrozenDict[str, Digest]:
        return FrozenDict({PythonBuildStandaloneBinary.SYMLINK_DIRNAME: self._digest})


# NB: These private types are solely so we can test the docker-path using the local
# environment.
class _PythonBuildStandaloneBinary(PythonBuildStandaloneBinary):
    pass


class _DownloadPythonBuildStandaloneBinaryRequest:
    pass


@rule
async def get_python_for_scripts(env_tgt: EnvironmentTarget) -> PythonBuildStandaloneBinary:
    if env_tgt.val is None or isinstance(env_tgt.val, LocalEnvironmentTarget):
        return PythonBuildStandaloneBinary(sys.executable, EMPTY_DIGEST)

    result = await Get(_PythonBuildStandaloneBinary, _DownloadPythonBuildStandaloneBinaryRequest())

    return PythonBuildStandaloneBinary(result.path, result._digest)


@rule(desc="Downloading Python for scripts", level=LogLevel.TRACE)
async def download_python_binary(
    _: _DownloadPythonBuildStandaloneBinaryRequest,
    platform: Platform,
    tar_binary: TarBinary,
    python_bootstrap: PythonBootstrapSubsystem,
) -> _PythonBuildStandaloneBinary:
    url, fingerprint, bytelen = python_bootstrap.internal_python_build_standalone_info[
        platform.value
    ]

    filename = url.rsplit("/", 1)[-1]
    python_archive = await Get(
        Digest,
        DownloadFile(
            url,
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

    return _PythonBuildStandaloneBinary(
        f"{PythonBuildStandaloneBinary.SYMLINK_DIRNAME}/python/bin/python3", result.output_digest
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
    return collect_rules()
