# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from textwrap import dedent  # noqa: PNT20

from pants.core.subsystems.python_bootstrap import PythonBootstrapSubsystem
from pants.core.util_rules.environments import EnvironmentTarget, LocalEnvironmentTarget
from pants.core.util_rules.system_binaries import BashBinary, SystemBinariesSubsystem, TarBinary
from pants.engine.fs import DownloadFile
from pants.engine.internals.native_engine import Digest, FileDigest
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
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

    _CACHE_DIRNAME = "python_build_standalone"
    _SYMLINK_DIRNAME = ".python-build-standalone"
    APPEND_ONLY_CACHES = FrozenDict({_CACHE_DIRNAME: _SYMLINK_DIRNAME})

    path: str  # The absolute path to a Python executable


# NB: These private types are solely so we can test the docker-path using the local
# environment.
class _PythonBuildStandaloneBinary(PythonBuildStandaloneBinary):
    pass


class _DownloadPythonBuildStandaloneBinaryRequest:
    pass


@rule
async def get_python_for_scripts(env_tgt: EnvironmentTarget) -> PythonBuildStandaloneBinary:
    if env_tgt.val is None or isinstance(env_tgt.val, LocalEnvironmentTarget):
        return PythonBuildStandaloneBinary(sys.executable)

    result = await Get(_PythonBuildStandaloneBinary, _DownloadPythonBuildStandaloneBinaryRequest())

    return PythonBuildStandaloneBinary(result.path)


@rule(desc="Downloading Python for scripts", level=LogLevel.TRACE)
async def download_python_binary(
    _: _DownloadPythonBuildStandaloneBinaryRequest,
    platform: Platform,
    tar_binary: TarBinary,
    bash_binary: BashBinary,
    python_bootstrap: PythonBootstrapSubsystem,
    system_binaries: SystemBinariesSubsystem,
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

    download_result = await Get(
        ProcessResult,
        Process(
            argv=[tar_binary.path, "-xvf", filename],
            input_digest=python_archive,
            env={"PATH": os.pathsep.join(system_binaries.EnvironmentAware.system_binary_paths)},
            description="Extract Pants' execution Python",
            level=LogLevel.DEBUG,
            output_directories=("python",),
        ),
    )

    installation_root = f"{PythonBuildStandaloneBinary._SYMLINK_DIRNAME}/{download_result.output_digest.fingerprint}"

    # NB: This is similar to what we do for every Python provider. We should refactor these into
    # some shared code to centralize the behavior.
    installation_script = dedent(
        f"""\
        if [ ! -f "{installation_root}/DONE" ]; then
            cp -r python "{installation_root}"
            touch "{installation_root}/DONE"
        fi
    """
    )

    await Get(
        ProcessResult,
        Process(
            [bash_binary.path, "-c", installation_script],
            level=LogLevel.DEBUG,
            input_digest=download_result.output_digest,
            description="Install Python for Pants usage",
            env={"PATH": os.pathsep.join(system_binaries.EnvironmentAware.system_binary_paths)},
            append_only_caches=PythonBuildStandaloneBinary.APPEND_ONLY_CACHES,
            # Don't cache, we want this to always be run so that we can assume for the rest of the
            # session the named_cache destination for this Python is valid, as the Python ecosystem
            # mainly assumes absolute paths for Python interpreters.
            cache_scope=ProcessCacheScope.PER_SESSION,
        ),
    )

    return _PythonBuildStandaloneBinary(f"{installation_root}/bin/python3")


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
