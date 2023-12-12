# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import shlex
import textwrap
from dataclasses import dataclass
from hashlib import sha256
from typing import ClassVar, Iterable, Tuple

from pants.core.util_rules import external_tool
from pants.core.util_rules.adhoc_binaries import PythonBuildStandaloneBinary
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.option.option_types import StrListOption, StrOption
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap

COURSIER_POST_PROCESSING_SCRIPT = textwrap.dedent(  # noqa: PNT20
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
        if not dep.get('file'):
            raise Exception(
                f"No jar found for {dep['coord']}. Check that it's available in the"
                + " repositories configured in [coursier].repos in pants.toml."
            )
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

COURSIER_FETCH_WRAPPER_SCRIPT = textwrap.dedent(  # noqa: PNT20
    """\
    set -eux

    coursier_exe="$1"
    shift
    json_output_file="$1"
    shift

    working_dir="$(pwd)"
    "$coursier_exe" fetch {repos_args} \
        --json-output-file="$json_output_file" \
        "${{@//{coursier_working_directory}/$working_dir}}"
    /bin/mkdir -p classpath
    {python_path} {coursier_bin_dir}/coursier_post_processing_script.py "$json_output_file"
    """
)


# TODO: Coursier renders setrlimit error line on macOS.
#   see https://github.com/pantsbuild/pants/issues/13942.
POST_PROCESS_COURSIER_STDERR_SCRIPT = textwrap.dedent(  # noqa: PNT20
    """\
    #!{python_path}
    import sys
    from subprocess import run, PIPE

    proc = run(sys.argv[1:], stdout=PIPE, stderr=PIPE)

    sys.stdout.buffer.write(proc.stdout)
    sys.stderr.buffer.write(proc.stderr.replace(b"setrlimit to increase file descriptor limit failed, errno 22\\n", b""))
    sys.exit(proc.returncode)
    """
)


class CoursierSubsystem(TemplatedExternalTool):
    options_scope = "coursier"
    name = "coursier"
    help = "A dependency resolver for the Maven ecosystem. (https://get-coursier.io/)"

    default_version = "v2.1.6"
    default_known_versions = [
        "v2.1.6|macos_arm64 |746b3e346fa2c0107fdbc8a627890d495cb09dee4f8dcc87146bdb45941088cf|20829782|https://github.com/VirtusLab/coursier-m1/releases/download/v2.1.6/cs-aarch64-apple-darwin.gz",
        "v2.1.6|linux_arm64 |33330ca433781c9db9458e15d2d32e5d795de3437771647e26835e8b1391af82|20899290|https://github.com/VirtusLab/coursier-m1/releases/download/v2.1.6/cs-aarch64-pc-linux.gz",
        "v2.1.6|linux_x86_64|af7234f8802107f5e1130307ef8a5cc90262d392f16ddff7dce27a4ed0ddd292|20681688",
        "v2.1.6|macos_x86_64|36a5d42a0724be2ac39d0ebd8869b985e3d58ceb121bc60389ee2d6d7408dd56|20037412",
        "v2.1.0-M5-18-gfebf9838c|linux_arm64 |d4ad15ba711228041ad8a46d848c83c8fbc421d7b01c415d8022074dd609760f|19264005",
        "v2.1.0-M5-18-gfebf9838c|linux_x86_64|3e1a1ad1010d5582e9e43c5a26b273b0147baee5ebd27d3ac1ab61964041c90b|19551533",
        "v2.1.0-M5-18-gfebf9838c|macos_arm64 |d13812c5a5ef4c9b3e25cc046d18addd09bacd149f95b20a14e4d2a73e358ecf|18826510",
        "v2.1.0-M5-18-gfebf9838c|macos_x86_64|d13812c5a5ef4c9b3e25cc046d18addd09bacd149f95b20a14e4d2a73e358ecf|18826510",
        "v2.0.16-169-g194ebc55c|linux_arm64 |da38c97d55967505b8454c20a90370c518044829398b9bce8b637d194d79abb3|18114472",
        "v2.0.16-169-g194ebc55c|linux_x86_64|4c61a634c4bd2773b4543fe0fc32210afd343692891121cddb447204b48672e8|18486946",
        "v2.0.16-169-g194ebc55c|macos_arm64 |15bce235d223ef1d022da30b67b4c64e9228d236b876c834b64e029bbe824c6f|17957182",
        "v2.0.16-169-g194ebc55c|macos_x86_64|15bce235d223ef1d022da30b67b4c64e9228d236b876c834b64e029bbe824c6f|17957182",
    ]
    default_url_template = (
        "https://github.com/coursier/coursier/releases/download/{version}/cs-{platform}.gz"
    )
    default_url_platform_mapping = {
        # By default we pull x86 binaries for Mac, since arm binaries
        # are unavailable for older supported versions of coursier. They work fine with rosetta.
        # For recent versions, arm binaries for mac and linux are available
        # at https://github.com/VirtusLab/coursier-m1/
        # Set the fifth field in known_versions to pull from this alternative source.
        "macos_arm64": "x86_64-apple-darwin",
        "macos_x86_64": "x86_64-apple-darwin",
        "linux_arm64": "aarch64-pc-linux",
        "linux_x86_64": "x86_64-pc-linux",
    }

    repos = StrListOption(
        default=[
            "https://maven-central.storage-download.googleapis.com/maven2",
            "https://repo1.maven.org/maven2",
        ],
        help=softwrap(
            """
            Maven style repositories to resolve artifacts from.

            Coursier will resolve these repositories in the order in which they are
            specified, and re-ordering repositories will cause artifacts to be
            re-downloaded. This can result in artifacts in lockfiles becoming invalid.
            """
        ),
    )

    jvm_index = StrOption(
        default="",
        help=softwrap(
            """
            The JVM index to be used by Coursier.

            Possible values are:
              - cs: The default JVM index used and maintained by Coursier.
              - cs-maven: Fetches a JVM index from the io.get-coursier:jvm-index Maven repository.
              - <URL>: An arbitrary URL for a JVM index. Ex. https://url/of/your/index.json
            """
        ),
    )

    def generate_exe(self, plat: Platform) -> str:
        tool_version = self.known_version(plat)
        url = (tool_version and tool_version.url_override) or self.generate_url(plat)
        archive_filename = os.path.basename(url)
        filename = os.path.splitext(archive_filename)[0]
        return f"./{filename}"


@dataclass(frozen=True)
class Coursier:
    """The Coursier tool and various utilities, prepared for use via `immutable_input_digests`."""

    coursier: DownloadedExternalTool
    _digest: Digest
    repos: FrozenOrderedSet[str]
    jvm_index: str
    _append_only_caches: FrozenDict[str, str]

    bin_dir: ClassVar[str] = "__coursier"
    fetch_wrapper_script: ClassVar[str] = f"{bin_dir}/coursier_fetch_wrapper_script.sh"
    post_processing_script: ClassVar[str] = f"{bin_dir}/coursier_post_processing_script.py"
    post_process_stderr: ClassVar[str] = f"{bin_dir}/coursier_post_process_stderr.py"
    cache_name: ClassVar[str] = "coursier"
    cache_dir: ClassVar[str] = ".cache"
    working_directory_placeholder: ClassVar[str] = "___COURSIER_WORKING_DIRECTORY___"

    def args(self, args: Iterable[str], *, wrapper: Iterable[str] = ()) -> tuple[str, ...]:
        return (
            self.post_process_stderr,
            *wrapper,
            os.path.join(self.bin_dir, self.coursier.exe),
            *args,
        )

    @memoized_property
    def _coursier_cache_prefix(self) -> str:
        """Returns a key for `COURSIER_CACHE` determined by the configured repositories.

        This helps us avoid a cache poisoning issue that we uncovered in #14577.
        """
        sha = sha256()
        for repo in self.repos:
            sha.update(repo.encode("utf-8"))
        return sha.digest().hex()

    @property
    def env(self) -> dict[str, str]:
        # NB: These variables have changed a few times, and they change again on `main`. But as of
        # `v2.0.16+73-gddc6d9cc9` they are accurate. See:
        #  https://github.com/coursier/coursier/blob/v2.0.16+73-gddc6d9cc9/modules/paths/src/main/java/coursier/paths/CoursierPaths.java#L38-L48
        return {
            # Maven artifacts and JDK tarballs go here
            "COURSIER_CACHE": f"{self.cache_dir}/{self._coursier_cache_prefix}/jdk",
            # extracted JDK tarballs go here
            "COURSIER_ARCHIVE_CACHE": f"{self.cache_dir}/arc",
            "COURSIER_JVM_CACHE": f"{self.cache_dir}/v1",
        }

    @property
    def append_only_caches(self) -> dict[str, str]:
        return {self.cache_name: self.cache_dir, **self._append_only_caches}

    @property
    def immutable_input_digests(self) -> dict[str, Digest]:
        return {self.bin_dir: self._digest}


@dataclass(frozen=True)
class CoursierFetchProcess:
    args: Tuple[str, ...]
    input_digest: Digest
    output_directories: Tuple[str, ...]
    output_files: Tuple[str, ...]
    description: str


@rule
async def invoke_coursier_wrapper(
    bash: BashBinary,
    coursier: Coursier,
    request: CoursierFetchProcess,
) -> Process:
    return Process(
        argv=coursier.args(
            request.args,
            wrapper=[bash.path, coursier.fetch_wrapper_script],
        ),
        input_digest=request.input_digest,
        immutable_input_digests=coursier.immutable_input_digests,
        output_directories=request.output_directories,
        output_files=request.output_files,
        append_only_caches=coursier.append_only_caches,
        env=coursier.env,
        description=request.description,
        level=LogLevel.DEBUG,
    )


@rule
async def setup_coursier(
    coursier_subsystem: CoursierSubsystem,
    python: PythonBuildStandaloneBinary,
    platform: Platform,
) -> Coursier:
    repos_args = (
        " ".join(f"-r={shlex.quote(repo)}" for repo in coursier_subsystem.repos) + " --no-default"
    )
    coursier_wrapper_script = COURSIER_FETCH_WRAPPER_SCRIPT.format(
        repos_args=repos_args,
        coursier_working_directory=Coursier.working_directory_placeholder,
        python_path=shlex.quote(python.path),
        coursier_bin_dir=shlex.quote(Coursier.bin_dir),
    )

    post_process_stderr = POST_PROCESS_COURSIER_STDERR_SCRIPT.format(python_path=python.path)

    downloaded_coursier_get = Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        coursier_subsystem.get_request(platform),
    )
    wrapper_scripts_digest_get = Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    os.path.basename(Coursier.fetch_wrapper_script),
                    coursier_wrapper_script.encode("utf-8"),
                    is_executable=True,
                ),
                FileContent(
                    os.path.basename(Coursier.post_processing_script),
                    COURSIER_POST_PROCESSING_SCRIPT.encode("utf-8"),
                    is_executable=True,
                ),
                FileContent(
                    os.path.basename(Coursier.post_process_stderr),
                    post_process_stderr.encode("utf-8"),
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
        repos=FrozenOrderedSet(coursier_subsystem.repos),
        jvm_index=coursier_subsystem.jvm_index,
        _append_only_caches=python.APPEND_ONLY_CACHES,
    )


def rules():
    return [
        *collect_rules(),
        *external_tool.rules(),
    ]
