# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
import re
import shlex
import textwrap
from dataclasses import dataclass
from typing import ClassVar, Iterable, Mapping

from pants.base.deprecated import warn_or_error
from pants.engine.fs import CreateDigest, Digest, FileContent, FileDigest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import BashBinary, FallibleProcessResult, Process, ProcessCacheScope
from pants.engine.rules import collect_rules, rule
from pants.engine.target import CoarsenedTarget
from pants.jvm.compile import ClasspathEntry
from pants.jvm.resolve.common import Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry
from pants.jvm.resolve.coursier_setup import Coursier
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmJdkField
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Nailgun:
    classpath_entry: ClasspathEntry


@dataclass(frozen=True)
class JdkRequest:
    """Request for a JDK with a specific major version, or None (use System JDK)."""

    version: str | JvmJdkField | None


@dataclass(frozen=True)
class JdkEnvironment:
    _digest: Digest
    nailgun_jar: str
    coursier: Coursier
    jre_major_version: int

    bin_dir: ClassVar[str] = "__jdk"
    jdk_preparation_script: ClassVar[str] = f"{bin_dir}/jdk.sh"
    java_home: ClassVar[str] = "__java_home"

    def args(self, bash: BashBinary, classpath_entries: Iterable[str]) -> tuple[str, ...]:
        return (
            bash.path,
            self.jdk_preparation_script,
            f"{self.java_home}/bin/java",
            "-cp",
            ":".join([self.nailgun_jar, *classpath_entries]),
        )

    @property
    def env(self) -> dict[str, str]:
        return self.coursier.env

    @property
    def append_only_caches(self) -> dict[str, str]:
        return self.coursier.append_only_caches

    @property
    def immutable_input_digests(self) -> dict[str, Digest]:
        return {**self.coursier.immutable_input_digests, self.bin_dir: self._digest}


@dataclass(frozen=True)
class InternalJdk(JdkEnvironment):
    """The JDK configured for internal Pants usage, rather than for matching source compatibility.
    
    The InternalJdk should only be used in situations where no classfiles are required for a user's
    firstparty or thirdparty code (such as for codegen, or analysis of source files).
    """


VERSION_REGEX = re.compile(r"version \"(.+?)\"")


def parse_jre_major_version(version_lines: str) -> int | None:
    for line in version_lines.splitlines():
        m = VERSION_REGEX.search(line)
        if m:
            major_version, _, _ = m[1].partition(".")
            return int(major_version)
    return None


@rule
async def fetch_nailgun() -> Nailgun:
    nailgun = await Get(
        ClasspathEntry,
        CoursierLockfileEntry(
            coord=Coordinate.from_coord_str("com.martiansoftware:nailgun-server:0.9.1"),
            file_name="com.martiansoftware_nailgun-server_0.9.1.jar",
            direct_dependencies=Coordinates(),
            dependencies=Coordinates(),
            file_digest=FileDigest(
                fingerprint="4518faa6bf4bd26fccdc4d85e1625dc679381a08d56872d8ad12151dda9cef25",
                serialized_bytes_length=32927,
            ),
        ),
    )

    return Nailgun(nailgun)


@rule
async def internal_jdk(jvm: JvmSubsystem) -> InternalJdk:
    """Creates a `JdkEnvironment` object based on the JVM subsystem options.

    This is used for providing a predictable JDK version for Pants' internal usage rather than for
    matching compatibility with source files (e.g. compilation/testing).
    """

    version = jvm.jdk if jvm.jdk != "system" else None

    env = await Get(JdkEnvironment, JdkRequest(version))
    return InternalJdk(env._digest, env.nailgun_jar, env.coursier, env.jre_major_version)


@rule
async def prepare_jdk_environment(
    jvm: JvmSubsystem, coursier: Coursier, nailgun_: Nailgun, bash: BashBinary, request: JdkRequest
) -> JdkEnvironment:
    nailgun = nailgun_.classpath_entry

    version = _resolve_jdk_request_to_version(request, jvm)

    # TODO: add support for system JDKs with specific version
    if version is None:
        coursier_jdk_option = "--system-jvm"
    else:
        coursier_jdk_option = shlex.quote(f"--jvm={version}")

    # TODO(#14386) This argument re-writing code should be done in a more standardised way.
    # See also `run_deploy_jar` for other argument re-writing code.
    def prefixed(arg: str) -> str:
        if arg.startswith("__"):
            return f"${{PANTS_INTERNAL_ABSOLUTE_PREFIX}}{arg}"
        else:
            return arg

    optionally_prefixed_coursier_args = [
        prefixed(arg) for arg in coursier.args(["java-home", coursier_jdk_option])
    ]
    # NB: We `set +e` in the subshell to ensure that it exits as well.
    #  see https://unix.stackexchange.com/a/23099
    java_home_command = " ".join(("set +e;", *optionally_prefixed_coursier_args))

    env = {
        "PANTS_INTERNAL_ABSOLUTE_PREFIX": "",
        **coursier.env,
    }

    java_version_result = await Get(
        FallibleProcessResult,
        Process(
            argv=(
                bash.path,
                "-c",
                f"$({java_home_command})/bin/java -version",
            ),
            append_only_caches=coursier.append_only_caches,
            immutable_input_digests=coursier.immutable_input_digests,
            env=env,
            description=f"Ensure download of JDK {coursier_jdk_option}.",
            cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL,
            level=LogLevel.DEBUG,
        ),
    )

    if java_version_result.exit_code != 0:
        raise ValueError(
            f"Failed to locate Java for JDK `{request.version}`:\n"
            f"{java_version_result.stderr.decode('utf-8')}"
        )

    java_version = java_version_result.stderr.decode("utf-8").strip()
    jre_major_version = parse_jre_major_version(java_version)
    if not jre_major_version:
        raise ValueError(
            "Pants was unable to parse the output of `java -version` for JDK "
            f"`{request.version}`. Please open an issue at "
            "https://github.com/pantsbuild/pants/issues/new/choose with the following output:\n\n"
            f"{java_version}"
        )

    # TODO: Locate `ln`.
    version_comment = "\n".join(f"# {line}" for line in java_version.splitlines())
    jdk_preparation_script = textwrap.dedent(
        f"""\
        # pants javac script using Coursier {coursier_jdk_option}. `java -version`:"
        {version_comment}
        set -eu

        /bin/ln -s "$({java_home_command})" "${{PANTS_INTERNAL_ABSOLUTE_PREFIX}}{JdkEnvironment.java_home}"
        exec "$@"
        """
    )
    jdk_preparation_script_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    os.path.basename(JdkEnvironment.jdk_preparation_script),
                    jdk_preparation_script.encode("utf-8"),
                    is_executable=True,
                ),
            ]
        ),
    )
    return JdkEnvironment(
        _digest=await Get(
            Digest,
            MergeDigests(
                [
                    jdk_preparation_script_digest,
                    nailgun.digest,
                ]
            ),
        ),
        nailgun_jar=os.path.join(JdkEnvironment.bin_dir, nailgun.filenames[0]),
        coursier=coursier,
        jre_major_version=jre_major_version,
    )


@frozen_after_init
@dataclass(unsafe_hash=True)
class JvmProcess:
    jdk: JdkEnvironment
    argv: tuple[str, ...]
    classpath_entries: tuple[str, ...]
    input_digest: Digest
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    extra_nailgun_keys: tuple[str, ...]
    output_files: tuple[str, ...]
    output_directories: tuple[str, ...]
    timeout_seconds: int | float | None
    platform: Platform | None
    extra_immutable_input_digests: FrozenDict[str, Digest]
    extra_env: FrozenDict[str, str]
    cache_scope: ProcessCacheScope | None
    use_nailgun: bool

    def __init__(
        self,
        jdk: JdkEnvironment,
        argv: Iterable[str],
        classpath_entries: Iterable[str],
        input_digest: Digest,
        description: str,
        level: LogLevel = LogLevel.INFO,
        extra_nailgun_keys: Iterable[str] | None = None,
        output_files: Iterable[str] | None = None,
        output_directories: Iterable[str] | None = None,
        extra_immutable_input_digests: Mapping[str, Digest] | None = None,
        extra_env: Mapping[str, str] | None = None,
        timeout_seconds: int | float | None = None,
        platform: Platform | None = None,
        cache_scope: ProcessCacheScope | None = None,
        use_nailgun: bool = True,
    ):
        self.jdk = jdk
        self.argv = tuple(argv)
        self.classpath_entries = tuple(classpath_entries)
        self.input_digest = input_digest
        self.description = description
        self.level = level
        self.extra_nailgun_keys = tuple(extra_nailgun_keys or ())
        self.output_files = tuple(output_files or ())
        self.output_directories = tuple(output_directories or ())
        self.timeout_seconds = timeout_seconds
        self.platform = platform
        self.cache_scope = cache_scope
        self.extra_immutable_input_digests = FrozenDict(extra_immutable_input_digests or {})
        self.extra_env = FrozenDict(extra_env or {})
        self.use_nailgun = use_nailgun

        if not use_nailgun and extra_nailgun_keys:
            raise AssertionError(
                "`JvmProcess` specified nailgun keys, but has `use_nailgun=False`. Either "
                "specify `extra_nailgun_keys=None` or `use_nailgun=True`."
            )


@rule
async def jvm_process(bash: BashBinary, request: JvmProcess) -> Process:

    jdk = request.jdk

    immutable_input_digests = {
        **jdk.immutable_input_digests,
        **request.extra_immutable_input_digests,
    }
    env = {
        "PANTS_INTERNAL_ABSOLUTE_PREFIX": "",
        **jdk.env,
        **request.extra_env,
    }

    use_nailgun = []
    if request.use_nailgun:
        use_nailgun = [*jdk.immutable_input_digests, *request.extra_nailgun_keys]

    return Process(
        [*jdk.args(bash, request.classpath_entries), *request.argv],
        input_digest=request.input_digest,
        immutable_input_digests=immutable_input_digests,
        use_nailgun=use_nailgun,
        description=request.description,
        level=request.level,
        output_directories=request.output_directories,
        env=env,
        platform=request.platform,
        timeout_seconds=request.timeout_seconds,
        append_only_caches=jdk.append_only_caches,
        output_files=request.output_files,
        cache_scope=request.cache_scope or ProcessCacheScope.SUCCESSFUL,
    )


@rule
async def jdk_request_for_target(target: CoarsenedTarget) -> JdkRequest:

    # TODO: verify that we're requesting the same JDK version for all `ct` members?
    t = target.representative

    if not t.has_field(JvmJdkField):
        raise ValueError(f"Cannot construct a JDK request for a non-JVM target {t}")

    field = t[JvmJdkField]

    return JdkRequest(field)


def _resolve_jdk_request_to_version(request: JdkRequest, defaults: JvmSubsystem) -> str | None:
    """Resolves the version value from `JdkRequest` into a usable JDK spec.

    If the return value is a string, it's a valid Coursier JDK spec. If `None`, Coursier will use
    `--system-jdk`.
    """

    if request.version is None:
        return None

    if isinstance(request.version, str):
        return request.version

    version = request.version.value
    if version is not None:
        return version

    default_source = defaults.default_source_jdk
    if default_source is not None:
        return default_source

    warn_or_error(
        "2.11.0.dev0",
        "support for empty `--jvm-default-source-jdk` values",
        (
            "Set `--jvm-default-source-jdk` to a version listed when you run "
            f"`cs java --available`. Alternatively, set the `{JvmJdkField.alias}` field on all JVM "
            "source targets in your `BUILD` files."
        ),
    )

    if defaults.jdk == "system":
        return None

    return defaults.jdk


def rules():
    return collect_rules()
