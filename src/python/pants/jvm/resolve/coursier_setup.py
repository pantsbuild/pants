# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import shlex
import textwrap
from dataclasses import dataclass
from typing import ClassVar, Iterable

from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.platform import Platform
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.python.binaries import PythonBinary

COURSIER_POST_PROCESSING_SCRIPT = textwrap.dedent(
    """\
    import json
    import sys
    import os
    from pathlib import PurePath
    from shutil import copyfile

    report = json.load(open(sys.argv[1]))

    # Mapping from dest path to source path. It is ok to capture the same output filename multiple
    # times if the source is the same as well.
    classpath = dict()
    for dep in report['dependencies']:
        source = PurePath(dep['file'])
        dest_name = dep['coord'].replace(":", "_")
        _, ext = os.path.splitext(source)
        classpath_dest = f"classpath/{dest_name}{ext}"

        existing_source = classpath.get(classpath_dest)
        if existing_source:
            if existing_source == source:
                # We've already captured this file.
                continue
            raise Exception(
                f"Duplicate jar name {classpath_dest} with incompatible source:\\n"
                f"  {source}\\n"
                f"  {existing_source}\\n"
            )
        classpath[classpath_dest] = source
        copyfile(source, classpath_dest)
    """
)


class CoursierSubsystem(TemplatedExternalTool):
    options_scope = "coursier"
    name = "coursier"
    help = "A dependency resolver for the Maven ecosystem."

    default_version = "v2.0.16-169-g194ebc55c"
    default_known_versions = [
        "v2.0.16-169-g194ebc55c|linux_arm64 |da38c97d55967505b8454c20a90370c518044829398b9bce8b637d194d79abb3|18114472",
        "v2.0.16-169-g194ebc55c|linux_x86_64|4c61a634c4bd2773b4543fe0fc32210afd343692891121cddb447204b48672e8|18486946",
        "v2.0.16-169-g194ebc55c|macos_arm64 |15bce235d223ef1d022da30b67b4c64e9228d236b876c834b64e029bbe824c6f|17957182",
        "v2.0.16-169-g194ebc55c|macos_x86_64|15bce235d223ef1d022da30b67b4c64e9228d236b876c834b64e029bbe824c6f|17957182",
    ]
    default_url_template = (
        "https://github.com/coursier/coursier/releases/download/{version}/cs-{platform}.gz"
    )
    default_url_platform_mapping = {
        "macos_arm64": "x86_64-apple-darwin",
        "macos_x86_64": "x86_64-apple-darwin",
        "linux_arm64": "aarch64-pc-linux",
        "linux_x86_64": "x86_64-pc-linux",
    }

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--repos",
            type=list,
            member_type=str,
            default=[
                "https://maven-central.storage-download.googleapis.com/maven2",
                "https://repo1.maven.org/maven2",
            ],
            help=("Maven style repositories to resolve artifacts from."),
        )

    def generate_exe(self, plat: Platform) -> str:
        archive_filename = os.path.basename(self.generate_url(plat))
        filename = os.path.splitext(archive_filename)[0]
        return f"./{filename}"


@dataclass(frozen=True)
class Coursier:
    """The Coursier tool and various utilities, prepared for use via `immutable_input_digests`."""

    coursier: DownloadedExternalTool
    _digest: Digest

    bin_dir: ClassVar[str] = "__coursier"
    wrapper_script: ClassVar[str] = f"{bin_dir}/coursier_wrapper_script.sh"
    post_processing_script: ClassVar[str] = f"{bin_dir}/coursier_post_processing_script.py"
    cache_name: ClassVar[str] = "coursier"
    cache_dir: ClassVar[str] = ".cache"
    working_directory_placeholder: ClassVar[str] = "___COURSIER_WORKING_DIRECTORY___"

    def args(self, args: Iterable[str], *, wrapper: Iterable[str] = ()) -> tuple[str, ...]:
        return tuple((*wrapper, os.path.join(self.bin_dir, self.coursier.exe), *args))

    @property
    def env(self) -> dict[str, str]:
        # NB: These variables have changed a few times, and they change again on `main`. But as of
        # `v2.0.16+73-gddc6d9cc9` they are accurate. See:
        #  https://github.com/coursier/coursier/blob/v2.0.16+73-gddc6d9cc9/modules/paths/src/main/java/coursier/paths/CoursierPaths.java#L38-L48
        return {
            "COURSIER_CACHE": f"{self.cache_dir}/jdk",
            "COURSIER_ARCHIVE_CACHE": f"{self.cache_dir}/arc",
            "COURSIER_JVM_CACHE": f"{self.cache_dir}/v1",
        }

    @property
    def append_only_caches(self) -> dict[str, str]:
        return {self.cache_name: self.cache_dir}

    @property
    def immutable_input_digests(self) -> dict[str, Digest]:
        return {self.bin_dir: self._digest}


@rule
async def setup_coursier(
    coursier_subsystem: CoursierSubsystem,
    python: PythonBinary,
) -> Coursier:
    repos_args = " ".join(f"-r={shlex.quote(repo)}" for repo in coursier_subsystem.options.repos)
    coursier_wrapper_script = textwrap.dedent(
        f"""\
        set -eux

        coursier_exe="$1"
        shift
        json_output_file="$1"
        shift

        working_dir="$(pwd)"
        "$coursier_exe" fetch {repos_args} \
          --json-output-file="$json_output_file" \
          "${{@//{Coursier.working_directory_placeholder}/$working_dir}}"
        /bin/mkdir -p classpath
        {python.path} {Coursier.bin_dir}/coursier_post_processing_script.py "$json_output_file"
        """
    )

    downloaded_coursier_get = Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        coursier_subsystem.get_request(Platform.current),
    )
    wrapper_scripts_digest_get = Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    os.path.basename(Coursier.wrapper_script),
                    coursier_wrapper_script.encode("utf-8"),
                    is_executable=True,
                ),
                FileContent(
                    os.path.basename(Coursier.post_processing_script),
                    COURSIER_POST_PROCESSING_SCRIPT.encode("utf-8"),
                    is_executable=True,
                ),
            ]
        ),
    )

    downloaded_coursier, wrapper_scripts_digest = await MultiGet(
        downloaded_coursier_get, wrapper_scripts_digest_get
    )

    return Coursier(
        coursier=downloaded_coursier,
        _digest=await Get(
            Digest,
            MergeDigests(
                [
                    downloaded_coursier.digest,
                    wrapper_scripts_digest,
                ]
            ),
        ),
    )


def rules():
    return [
        *collect_rules(),
        *external_tool.rules(),
    ]
