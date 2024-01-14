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
from enum import Enum
from typing import ClassVar, Iterable, Mapping

from pants.core.util_rules.environments import EnvironmentTarget
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.fs import CreateDigest, Digest, FileContent, FileDigest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope
from pants.engine.rules import collect_rules, rule
from pants.engine.target import CoarsenedTarget
from pants.jvm.compile import ClasspathEntry
from pants.jvm.resolve.coordinate import Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry
from pants.jvm.resolve.coursier_setup import Coursier
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmJdkField
from pants.option.global_options import GlobalOptions
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.strutil import fmt_memory_size, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Nailgun:
    classpath_entry: ClasspathEntry


class DefaultJdk(Enum):
    SYSTEM = "system"
    SOURCE_DEFAULT = "source_default"


@dataclass(frozen=True)
class JdkRequest:
    """Request for a JDK with a specific major version, or a default (`--jvm-jdk` or System)."""

    version: str | DefaultJdk

    @classproperty
    def SYSTEM(cls) -> JdkRequest:
        return JdkRequest(DefaultJdk.SYSTEM)

    @classproperty
    def SOURCE_DEFAULT(cls) -> JdkRequest:
        return JdkRequest(DefaultJdk.SOURCE_DEFAULT)

    @staticmethod
    def from_field(field: JvmJdkField) -> JdkRequest:
        version = field.value
        if version == "system":
            return JdkRequest.SYSTEM
        return JdkRequest(version) if version is not None else JdkRequest.SOURCE_DEFAULT

    @staticmethod
    def from_target(target: CoarsenedTarget) -> JdkRequest:
        fields = [t[JvmJdkField] for t in target.members if t.has_field(JvmJdkField)]

        if not fields:
            raise ValueError(
                f"Cannot construct a JDK request for {target}, since none of its "
                f"members have a `{JvmJdkField.alias}=` field:\n{target.bullet_list()}"
            )

        field = fields[0]
        if not all(f.value == field.value for f in fields):
            values = {f.value for f in fields}
            raise ValueError(
                f"The members of {target} had mismatched values of the "
                f"`{JvmJdkField.alias}=` field ({values}):\n{target.bullet_list()}"
            )

        return JdkRequest.from_field(field)


@dataclass(frozen=True)
class JdkEnvironment:
    _digest: Digest
    nailgun_jar: str
    coursier: Coursier
    jre_major_version: int
    global_jvm_options: tuple[str, ...]
    java_home_command: str

    bin_dir: ClassVar[str] = "__jdk"
    jdk_preparation_script: ClassVar[str] = f"{bin_dir}/jdk.sh"
    java_home: ClassVar[str] = "__java_home"

    def args(
        self, bash: BashBinary, classpath_entries: Iterable[str], chroot: str | None = None
    ) -> tuple[str, ...]:
        def in_chroot(path: str) -> str:
            if not chroot:
                return path
            return os.path.join(chroot, path)

        return (
            bash.path,
            in_chroot(self.jdk_preparation_script),
            f"{self.java_home}/bin/java",
            "-cp",
            ":".join([in_chroot(self.nailgun_jar), *classpath_entries]),
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

    @classmethod
    def from_jdk_environment(cls, env: JdkEnvironment) -> InternalJdk:
        return cls(
            env._digest,
            env.nailgun_jar,
            env.coursier,
            env.jre_major_version,
            env.global_jvm_options,
            env.java_home_command,
        )


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

    request = JdkRequest(jvm.tool_jdk) if jvm.tool_jdk is not None else JdkRequest.SYSTEM
    env = await Get(JdkEnvironment, JdkRequest, request)
    return InternalJdk.from_jdk_environment(env)


@rule
async def prepare_jdk_environment(
    jvm: JvmSubsystem,
    jvm_env_aware: JvmSubsystem.EnvironmentAware,
    coursier: Coursier,
    nailgun_: Nailgun,
    bash: BashBinary,
    request: JdkRequest,
    env_target: EnvironmentTarget,
) -> JdkEnvironment:
    nailgun = nailgun_.classpath_entry

    version = request.version
    if version == DefaultJdk.SOURCE_DEFAULT:
        version = jvm.jdk

    # TODO: add support for system JDKs with specific version
    if version is DefaultJdk.SYSTEM:
        coursier_jdk_option = "--system-jvm"
    else:
        coursier_jdk_option = f"--jvm={version}"

    if not coursier.jvm_index:
        coursier_options = ["java-home", coursier_jdk_option]
    else:
        jvm_index_option = f"--jvm-index={coursier.jvm_index}"
        coursier_options = ["java-home", jvm_index_option, coursier_jdk_option]

    # TODO(#16104) This argument re-writing code should use the native {chroot} support.
    # See also `run` for other argument re-writing code.
    def prefixed(arg: str) -> str:
        if arg.startswith("__"):
            return f"${{PANTS_INTERNAL_ABSOLUTE_PREFIX}}{arg}"
        else:
            return arg

    optionally_prefixed_coursier_args = [
        prefixed(shlex.quote(arg)) for arg in coursier.args(coursier_options)
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
            cache_scope=env_target.executable_search_path_cache_scope(),
            level=LogLevel.DEBUG,
        ),
    )

    if java_version_result.exit_code != 0:
        raise ValueError(
            f"Failed to locate Java for JDK `{version}`:\n"
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
    jdk_preparation_script = textwrap.dedent(  # noqa: PNT20
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
        global_jvm_options=jvm_env_aware.global_options,
        nailgun_jar=os.path.join(JdkEnvironment.bin_dir, nailgun.filenames[0]),
        coursier=coursier,
        jre_major_version=jre_major_version,
        java_home_command=java_home_command,
    )


@dataclass(frozen=True)
class JvmProcess:
    jdk: JdkEnvironment
    argv: tuple[str, ...]
    classpath_entries: tuple[str, ...]
    input_digest: Digest
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    extra_jvm_options: tuple[str, ...]
    extra_nailgun_keys: tuple[str, ...]
    output_files: tuple[str, ...]
    output_directories: tuple[str, ...]
    timeout_seconds: int | float | None
    extra_immutable_input_digests: FrozenDict[str, Digest]
    extra_env: FrozenDict[str, str]
    cache_scope: ProcessCacheScope | None
    use_nailgun: bool
    remote_cache_speculation_delay: int | None

    def __init__(
        self,
        jdk: JdkEnvironment,
        argv: Iterable[str],
        classpath_entries: Iterable[str],
        input_digest: Digest,
        description: str,
        level: LogLevel = LogLevel.INFO,
        extra_jvm_options: Iterable[str] | None = None,
        extra_nailgun_keys: Iterable[str] | None = None,
        output_files: Iterable[str] | None = None,
        output_directories: Iterable[str] | None = None,
        extra_immutable_input_digests: Mapping[str, Digest] | None = None,
        extra_env: Mapping[str, str] | None = None,
        timeout_seconds: int | float | None = None,
        cache_scope: ProcessCacheScope | None = None,
        use_nailgun: bool = True,
        remote_cache_speculation_delay: int | None = None,
    ):
        object.__setattr__(self, "jdk", jdk)
        object.__setattr__(self, "argv", tuple(argv))
        object.__setattr__(self, "classpath_entries", tuple(classpath_entries))
        object.__setattr__(self, "input_digest", input_digest)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "extra_jvm_options", tuple(extra_jvm_options or ()))
        object.__setattr__(self, "extra_nailgun_keys", tuple(extra_nailgun_keys or ()))
        object.__setattr__(self, "output_files", tuple(output_files or ()))
        object.__setattr__(self, "output_directories", tuple(output_directories or ()))
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "cache_scope", cache_scope)
        object.__setattr__(
            self, "extra_immutable_input_digests", FrozenDict(extra_immutable_input_digests or {})
        )
        object.__setattr__(self, "extra_env", FrozenDict(extra_env or {}))
        object.__setattr__(self, "use_nailgun", use_nailgun)
        object.__setattr__(self, "remote_cache_speculation_delay", remote_cache_speculation_delay)

        self.__post_init__()

    def __post_init__(self):
        if not self.use_nailgun and self.extra_nailgun_keys:
            raise AssertionError(
                "`JvmProcess` specified nailgun keys, but has `use_nailgun=False`. Either "
                "specify `extra_nailgun_keys=None` or `use_nailgun=True`."
            )


_JVM_HEAP_SIZE_UNITS = ["", "k", "m", "g"]


@rule
async def jvm_process(
    bash: BashBinary, request: JvmProcess, jvm: JvmSubsystem, global_options: GlobalOptions
) -> Process:
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

    def valid_jvm_opt(opt: str) -> str:
        if opt.startswith("-Xmx"):
            raise ValueError(
                softwrap(
                    f"""
                    Invalid value for JVM options: {opt}.

                    For setting a maximum heap size for the JVM child processes, use
                    `[GLOBAL].process_per_child_memory_usage` option instead.

                    Run `{bin_name()} help-advanced global` for more information.
                    """
                )
            )
        return opt

    max_heap_size = fmt_memory_size(
        global_options.process_per_child_memory_usage, units=_JVM_HEAP_SIZE_UNITS
    )
    jvm_user_options = [*jdk.global_jvm_options, *request.extra_jvm_options]
    jvm_options = [
        f"-Xmx{max_heap_size}",
        *[valid_jvm_opt(opt) for opt in jvm_user_options],
    ]

    use_nailgun = []
    if request.use_nailgun:
        use_nailgun = [*jdk.immutable_input_digests, *request.extra_nailgun_keys]

    remote_cache_speculation_delay_millis = 0
    if request.remote_cache_speculation_delay is not None:
        remote_cache_speculation_delay_millis = request.remote_cache_speculation_delay
    elif request.use_nailgun:
        remote_cache_speculation_delay_millis = jvm.nailgun_remote_cache_speculation_delay

    return Process(
        [*jdk.args(bash, request.classpath_entries), *jvm_options, *request.argv],
        input_digest=request.input_digest,
        immutable_input_digests=immutable_input_digests,
        use_nailgun=use_nailgun,
        description=request.description,
        level=request.level,
        output_directories=request.output_directories,
        env=env,
        timeout_seconds=request.timeout_seconds,
        append_only_caches=jdk.append_only_caches,
        output_files=request.output_files,
        cache_scope=request.cache_scope or ProcessCacheScope.SUCCESSFUL,
        remote_cache_speculation_delay_millis=remote_cache_speculation_delay_millis,
    )


def rules():
    return collect_rules()
