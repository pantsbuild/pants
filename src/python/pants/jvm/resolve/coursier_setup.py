# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import ClassVar, Iterable

from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.platform import Platform
from pants.engine.rules import Get, MultiGet, collect_rules, rule

COURSIER_POST_PROCESSING_SCRIPT = textwrap.dedent(
    """\
    import json
    import sys
    from pathlib import PurePath
    from shutil import copyfile

    report = json.load(open(sys.argv[1]))

    classpath = set()
    for dep in report['dependencies']:
        file_path = PurePath(dep['file'])
        classpath_dest = f"classpath/{file_path.name}"
        if classpath_dest in classpath:
            raise Exception(f"Found duplicate jar name {file_path.name}, which isn't currently supported")
        classpath.add(classpath_dest)
        copyfile(file_path, classpath_dest)
    """
)

COURSIER_WRAPPER_SCRIPT = textwrap.dedent(
    """\
    set -eux

    coursier_exe="$1"
    shift
    json_output_file="$1"
    shift

    "$coursier_exe" fetch --json-output-file="$json_output_file" "$@"

    /bin/mkdir -p classpath
    /usr/bin/python3 coursier_post_processing_script.py "$json_output_file"
    """
)


class CoursierBinary(TemplatedExternalTool):
    options_scope = "coursier"
    name = "coursier"
    help = "A dependency resolver for the Maven ecosystem."

    default_version = "v2.0.13"
    default_known_versions = [
        "v2.0.13|linux_arm64 |8d428bede2d9d0e48ffad8360d49de48bd0c2c3b0e54e82e3a7665019b65e4d0|58622664",
        "v2.0.13|linux_x86_64|1ae089789cc4b0a4d296d6852b760d7f8bf72805267a6b7571e99b681d5e13b4|59652208",
        "v2.0.13|macos_arm64 |d74b8fe4ffc2f4e9011d7151722fc8b5ffca8a72b3bc4188c61df3326228c4ef|57625024",
        "v2.0.13|macos_x86_64|d74b8fe4ffc2f4e9011d7151722fc8b5ffca8a72b3bc4188c61df3326228c4ef|57625024",
    ]
    default_url_template = (
        "https://github.com/coursier/coursier/releases/download/{version}/cs-{platform}"
    )
    default_url_platform_mapping = {
        "macos_arm64": "x86_64-apple-darwin",
        "macos_x86_64": "x86_64-apple-darwin",
        "linux_arm64": "aarch64-pc-linux",
        "linux_x86_64": "x86_64-pc-linux",
    }


@dataclass(frozen=True)
class Coursier:
    """The Coursier tool and various utilities, materialzed to a `Digest` and ready to use."""

    coursier: DownloadedExternalTool
    digest: Digest
    wrapper_script: ClassVar[str] = "coursier_wrapper_script.sh"
    post_processing_script: ClassVar[str] = "coursier_post_processing_script.py"
    cache_name: ClassVar[str] = "coursier"
    cache_dir: ClassVar[str] = ".cache"

    def args(self, args: Iterable[str], *, wrapper: Iterable[str] = ()) -> tuple[str, ...]:
        return tuple((*wrapper, self.coursier.exe, *args, "--cache", f"{self.cache_dir}"))

    @property
    def append_only_caches(self) -> dict[str, str]:
        return {self.cache_name: self.cache_dir}


@rule
async def setup_coursier(coursier_binary: CoursierBinary) -> Coursier:
    downloaded_coursier_get = Get(
        DownloadedExternalTool, ExternalToolRequest, coursier_binary.get_request(Platform.current)
    )
    wrapper_scripts_digest_get = Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    Coursier.wrapper_script,
                    COURSIER_WRAPPER_SCRIPT.encode("utf-8"),
                    is_executable=True,
                ),
                FileContent(
                    Coursier.post_processing_script,
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
        digest=await Get(
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
    return [*collect_rules()]
