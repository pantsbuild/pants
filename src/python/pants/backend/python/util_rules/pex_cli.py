# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os.path
import shlex
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import ClassVar, Iterable, Mapping, Optional, Tuple

from pants.backend.python.subsystems.python_native_code import PythonNativeCodeSubsystem
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules import pex_environment
from pants.backend.python.util_rules.pex_environment import PexEnvironment, PexSubsystem
from pants.base.build_root import BuildRoot
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules import adhoc_binaries, external_tool, system_binaries
from pants.core.util_rules.adhoc_binaries import PythonBuildStandaloneBinary
from pants.core.util_rules.environments import EnvironmentTarget
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.fs import CreateDigest, Digest, Directory, FileContent, MergeDigests
from pants.engine.internals.selectors import MultiGet
from pants.engine.internals.session import RunId
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, _uncacheable_rule, collect_rules, rule
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.global_options import GlobalOptions, ca_certs_path_to_file_content
from pants.option.option_types import ArgsListOption
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class PexCli(TemplatedExternalTool):
    options_scope = "pex-cli"
    name = "pex"
    help = "The PEX (Python EXecutable) tool (https://github.com/pex-tool/pex)."

    default_version = "v2.29.0"
    default_url_template = "https://github.com/pex-tool/pex/releases/download/{version}/pex"
    version_constraints = ">=2.13.0,<3.0"

    # extra args to be passed to the pex tool; note that they
    # are going to apply to all invocations of the pex tool.
    global_args = ArgsListOption(
        example="--check=error --no-compile",
        extra_help=softwrap(
            """
            Note that these apply to all invocations of the pex tool, including building `pex_binary`
            targets, preparing `python_test` targets to run, and generating lockfiles.
            """
        ),
    )

    @classproperty
    def default_known_versions(cls):
        return [
            "|".join(
                (
                    cls.default_version,
                    plat,
                    "8307cb6f5ce09f82e4f5e7858428237cb6440fc91fcb723dc1e09cb2d57e2c2f",
                    "4370181",
                )
            )
            for plat in ["macos_arm64", "macos_x86_64", "linux_x86_64", "linux_arm64"]
        ]


@dataclass(frozen=True)
class PexCliProcess:
    subcommand: tuple[str, ...]
    extra_args: tuple[str, ...]
    description: str = dataclasses.field(compare=False)
    additional_input_digest: Optional[Digest]
    extra_env: Optional[FrozenDict[str, str]]
    output_files: Optional[Tuple[str, ...]]
    output_directories: Optional[Tuple[str, ...]]
    level: LogLevel
    concurrency_available: int
    cache_scope: ProcessCacheScope

    def __init__(
        self,
        *,
        subcommand: Iterable[str],
        extra_args: Iterable[str],
        description: str,
        additional_input_digest: Optional[Digest] = None,
        extra_env: Optional[Mapping[str, str]] = None,
        output_files: Optional[Iterable[str]] = None,
        output_directories: Optional[Iterable[str]] = None,
        level: LogLevel = LogLevel.INFO,
        concurrency_available: int = 0,
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
        with_keyring_trampoline: bool = False,
    ) -> None:
        object.__setattr__(self, "subcommand", tuple(subcommand))
        object.__setattr__(self, "extra_args", tuple(extra_args))
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "additional_input_digest", additional_input_digest)
        object.__setattr__(self, "extra_env", FrozenDict(extra_env) if extra_env else None)
        object.__setattr__(self, "output_files", tuple(output_files) if output_files else None)
        object.__setattr__(
            self, "output_directories", tuple(output_directories) if output_directories else None
        )
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "concurrency_available", concurrency_available)
        object.__setattr__(self, "cache_scope", cache_scope)

        self.__post_init__()

    def __post_init__(self) -> None:
        if "--pex-root-path" in self.extra_args:
            raise ValueError("`--pex-root` flag not allowed. We set its value for you.")


@union
@dataclass(frozen=True)
class PexKeyringConfigurationRequest:
    """Request sent to keyring plugins to request credentials to expose to Pex/Pip."""

    name: ClassVar[str]


@dataclass(frozen=True)
class PexKeyringConfigurationResponse:
    """Response containing credentials to expose to Pex/Pip via simulating the `keyring` package's
    binary."""

    # Nested map from SITE -> USER -> PASSWORD.
    credentials: FrozenDict[str, tuple[str, str]] | None


# The following script is injected into any Pex CLI process where credentials will be exposed via
# the `keyring` package. Pip will be configured to use its `subprocess` mode which will obtain
# credentials by invoking this "keyring" binary from the PATH.
#
# Credentials are stored in the file stored in the `__PANTS_KEYRING_DATA` environment variable.
# The file is sourced to define a `pants_keyring_credentials` associate array.
_KEYRING_SCRIPT = """\
#!__BASH_PATH__
if [ "$1" != "get" ]; then
  echo "ERROR: The `keyring` trampoline script only supports the `get` subcommand." 1>&2
  exit 111
fi
shift

if [ -z "$__PANTS_KEYRING_DATA" ]; then
  echo "ERROR: __PANTS_KEYRING_DATA env var was not set." 1>&2
  exit 111
fi

if [ ! -e "$__PANTS_KEYRING_DATA" ]; then
  echo "ERROR: __PANTS_KEYRING_DATA file '${__PANTS_KEYRING_DATA}' does not exist." 1>&2
  exit 111
fi
source "$__PANTS_KEYRING_DATA"

if [ -z "$1" ]; then
  echo "ERROR: Site not provided on command-line." 1>&2
  exit 111
fi
site="$1"
shift

if [ -z "$1" ]; then
  echo "ERROR: User not provided on command-line." 1>&2
  exit 111
fi
user="$1"
shift

password="${pants_keyring_credentials[$site:$user]}"
if [ -z "$password" ]; then
  # If the password is not set, then ordinary `keyring` exits with no output and code 1.
  exit 1
fi

echo "$password"
exit 0
"""


class PexPEX(DownloadedExternalTool):
    """The Pex PEX binary."""


@rule
async def download_pex_pex(pex_cli: PexCli, platform: Platform) -> PexPEX:
    pex_pex = await Get(DownloadedExternalTool, ExternalToolRequest, pex_cli.get_request(platform))
    return PexPEX(digest=pex_pex.digest, exe=pex_pex.exe)


@dataclass(frozen=True)
class _KeyringScript:
    digest: Digest


@rule
async def setup_keyring_script(bash: BashBinary) -> _KeyringScript:
    digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    path=".keyring/keyring",
                    content=_KEYRING_SCRIPT.replace("__BASH_PATH__", bash.path).encode(),
                    is_executable=True,
                )
            ]
        ),
    )
    return _KeyringScript(digest=digest)


@dataclass(frozen=True)
class _KeyringState:
    keyring_data_path: Path | None


def _always_shlex_quote(str: str) -> str:
    shlexed_str = shlex.quote(str)
    if shlexed_str != str:
        return shlexed_str
    return f"'{str}'"


@_uncacheable_rule
async def setup_keyring_state(
    union_membership: UnionMembership,
    env_tgt: EnvironmentTarget,
    build_root: BuildRoot,
    run_id: RunId,
) -> _KeyringState:
    # TODO: Consider how to enable credential injection in remote execution and other contexts
    # where Pants rule code cannot directly control where the credentials are stored.
    if not env_tgt.can_access_local_system_paths:
        return _KeyringState(keyring_data_path=None)

    keyring_plugin_request_types = union_membership.get(PexKeyringConfigurationRequest)
    if not keyring_plugin_request_types:
        return _KeyringState(keyring_data_path=None)

    credentials_responses: dict[str, list[tuple[str, tuple[str, str]]]] = {}
    for keyring_plugin_request_type in keyring_plugin_request_types:
        keyring_plugin_request = keyring_plugin_request_type()
        keyring_plugin_response = await Get(  # noqa: PNT30: Only one provider expected.
            PexKeyringConfigurationResponse, PexKeyringConfigurationRequest, keyring_plugin_request
        )

        keyring_plugin_credentials = keyring_plugin_response.credentials
        if not keyring_plugin_credentials:
            continue

        for site, user_password in keyring_plugin_credentials.items():
            if site not in credentials_responses:
                credentials_responses[site] = []
            credentials_responses[site].append((keyring_plugin_request_type.name, user_password))

    # Check for multiple responses for a single site. Keyring and our simulation of it only supports
    # a single user/password per site.
    credentials: list[tuple[str, str, str]] = []
    for site, user_password_creds_by_provider in credentials_responses.items():
        if len(user_password_creds_by_provider) > 1:
            providers = [x[0] for x in user_password_creds_by_provider]
            raise Exception(
                f"Multiple keyring plugins returned responses for `{site}`. "
                "The keyring support only supports a single user/password per site. "
                f"The keyring plugins in conflict are: {', '.join(providers)}."
            )
        user_password_creds = user_password_creds_by_provider[0][1]
        credentials.append((site, user_password_creds[0], user_password_creds[1]))
    credentials.sort()

    # Write the credentials to a file based on the current session ID.
    content = StringIO()
    content.write("declare -A pants_keyring_credentials\n")
    for site, user, password in credentials:
        content.write(
            f"pants_keyring_credentials[{_always_shlex_quote(site)}]={_always_shlex_quote(user)}\n"
        )
        site_user = f"{site}:{user}"
        content.write(
            f"pants_keyring_credentials[{_always_shlex_quote(site_user)}]={_always_shlex_quote(password)}\n"
        )

    # TODO: Consider removing the run ID so that this value does not contribute to the cache key
    # and cause unneeded invalidation of build actions as it changes for each run.
    keyring_data_path = build_root.pathlib_path / ".pants.d" / "keyring" / str(run_id) / "data.sh"
    keyring_data_path.parent.mkdir(parents=True, exist_ok=True)
    keyring_data_path.write_bytes(content.getvalue().encode())

    return _KeyringState(keyring_data_path=keyring_data_path)


@rule
async def setup_pex_cli_process(
    request: PexCliProcess,
    pex_pex: PexPEX,
    pex_env: PexEnvironment,
    bootstrap_python: PythonBuildStandaloneBinary,
    python_native_code: PythonNativeCodeSubsystem.EnvironmentAware,
    global_options: GlobalOptions,
    pex_subsystem: PexSubsystem,
    pex_cli_subsystem: PexCli,
    python_setup: PythonSetup,
) -> Process:
    tmpdir = ".tmp"

    digests_to_merge = [pex_pex.digest]
    digest_gets: list[Get] = [Get(Digest, CreateDigest([Directory(tmpdir)]))]

    cert_args = []
    if global_options.ca_certs_path:
        ca_certs_fc = ca_certs_path_to_file_content(global_options.ca_certs_path)
        digest_gets.append(Get(Digest, CreateDigest((ca_certs_fc,))))
        cert_args = ["--cert", ca_certs_fc.path]

    keyring_state = await Get(_KeyringState)
    keyring_args: list[str] = []
    if keyring_state.keyring_data_path:
        keyring_script = await Get(_KeyringScript)
        digests_to_merge.append(keyring_script.digest)
        keyring_args.append("--keyring-provider=subprocess")

    digests_to_merge.extend(await MultiGet(digest_gets))
    if request.additional_input_digest:
        digests_to_merge.append(request.additional_input_digest)
    input_digest = await Get(Digest, MergeDigests(digests_to_merge))

    global_args = [
        # Ensure Pex and its subprocesses create temporary files in the process execution
        # sandbox. It may make sense to do this generally for Processes, but in the short term we
        # have known use cases where /tmp is too small to hold large wheel downloads Pex is asked to
        # perform. Making the TMPDIR local to the sandbox allows control via
        # --local-execution-root-dir for the local case and should work well with remote cases where
        # a remoting implementation has to allow for processes producing large binaries in a
        # sandbox to support reasonable workloads. Communicating TMPDIR via --tmpdir instead of via
        # environment variable allows Pex to absolutize the path ensuring subprocesses that change
        # CWD can find the TMPDIR.
        "--tmpdir",
        tmpdir,
    ]

    if request.concurrency_available > 0:
        global_args.extend(["--jobs", "{pants_concurrency}"])

    verbosity_args = [f"-{'v' * pex_subsystem.verbosity}"] if pex_subsystem.verbosity > 0 else []

    warnings_args = [] if pex_subsystem.emit_warnings else ["--no-emit-warnings"]

    # NB: We should always pass `--python-path`, as that tells Pex where to look for interpreters
    # when `--python` isn't an absolute path.
    resolve_args = [
        *cert_args,
        "--python-path",
        os.pathsep.join(pex_env.interpreter_search_paths),
    ]
    # All old-style pex runs take the --pip-version flag, but only certain subcommands of the
    # `pex3` console script do. So if invoked with a subcommand, the caller must selectively
    # set --pip-version only on subcommands that take it.
    # pip_version_args = [] if request.subcommand else ["--pip-version", python_setup.pip_version]
    pip_version_args = ["--pip-version", python_setup.pip_version]
    args = [
        *request.subcommand,
        *keyring_args,
        *global_args,
        *verbosity_args,
        *warnings_args,
        *pip_version_args,
        *resolve_args,
        *pex_cli_subsystem.global_args,
        # NB: This comes at the end because it may use `--` passthrough args, # which must come at
        # the end.
        *request.extra_args,
    ]

    complete_pex_env = pex_env.in_sandbox(working_directory=None)
    normalized_argv = complete_pex_env.create_argv(pex_pex.exe, *args)
    env = {
        **complete_pex_env.environment_dict(python=bootstrap_python),
        **python_native_code.subprocess_env_vars,
        **(request.extra_env or {}),  # type: ignore[dict-item]
        # If a subcommand is used, we need to use the `pex3` console script.
        **({"PEX_SCRIPT": "pex3"} if request.subcommand else {}),
    }

    if keyring_state.keyring_data_path:
        env["__PANTS_KEYRING_DATA"] = str(keyring_state.keyring_data_path)
        # TODO: Get the path from the keyring script dataclass.
        if "PATH" in env:
            env["PATH"] = f"{{chroot}}/.keyring:{env['PATH']}"
        else:
            env["PATH"] = "{chroot}/.keyring"

    return Process(
        normalized_argv,
        description=request.description,
        input_digest=input_digest,
        env=env,
        output_files=request.output_files,
        output_directories=request.output_directories,
        append_only_caches=complete_pex_env.append_only_caches,
        level=request.level,
        concurrency_available=request.concurrency_available,
        cache_scope=request.cache_scope,
    )


def maybe_log_pex_stderr(stderr: bytes, pex_verbosity: int) -> None:
    """Forward Pex's stderr to a Pants logger if conditions are met."""
    log_output = stderr.decode()
    if log_output and "PEXWarning:" in log_output:
        logger.warning("%s", log_output)
    elif log_output and pex_verbosity > 0:
        logger.info("%s", log_output)


def rules():
    return [
        *collect_rules(),
        *external_tool.rules(),
        *pex_environment.rules(),
        *adhoc_binaries.rules(),
        *system_binaries.rules(),
        UnionRule(ExportableTool, PexCli),
    ]
