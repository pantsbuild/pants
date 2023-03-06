# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
from dataclasses import dataclass
from textwrap import dedent  # noqa: PNT20

from pants.backend.python.providers.pyenv.target_types import PyenvInstallSentinelField
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules.pex import PythonProvider
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.core.util_rules.external_tool import rules as external_tools_rules
from pants.core.util_rules.system_binaries import PythonBinary
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.internals.synthetic_targets import SyntheticAddressMaps, SyntheticTargetsRequest
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.meta import classproperty
from pants.util.strutil import softwrap

PYENV_NAMED_CACHE = ".pyenv"
PYENV_APPEND_ONLY_CACHES = FrozenDict({"pyenv": PYENV_NAMED_CACHE})


class PyenvPythonProviderSubsystem(TemplatedExternalTool):
    options_scope = "pyenv-python-provider"
    name = "pyenv"
    help = softwrap(
        f"""
        A subsystem for Pants-provided Python leveraging pyenv (https://github.com/pyenv/pyenv).

        Enabling this subsystem will switch Pants from trying to find an appropriate Python on your
        system to using pyenv to install the correct Python(s).

        The Pythons provided by Pyenv will be used to run any "user" code (your Python code as well
        as any Python-based tools you use, like black or pylint). The Pythons are also read-only to
        ensure they remain hermetic across runs of different tools and code.

        The Pythons themselves are stored in your `named_caches_dir`: https://www.pantsbuild.org/docs/reference-global#named_caches_dir
        under `pyenv/versions/<version>`. Wiping the relevant version directory (with `sudo rm -rf`)
        will force a re-install of Python. This may be necessary after changing something about the
        underlying system which changes the compiled Python, such as installing an
        optional-at-build-time dependency like `liblzma-dev` (which is used for the optional module
        `lzma`).

        By default, the subsystem does not pass any optimization flags to the Python compilation
        process. Doing so would increase the time it takes to install a single Python by about an
        order of magnitude (E.g. ~2.5 minutes to ~26 minutes).

        If you wish to customize the pyenv installation of a Python, a synthetic target is exposed
        at the root of your repo which is runnable. This target can be run with the relevant
        environment variables set to enable optimizations. You will need to wipe the specific
        version directory if Python was already installed. Example:

            sudo rm -rf <named_caches_dir>/pyenv/versions/<specific_version>
            # env vars from https://github.com/pyenv/pyenv/blob/master/plugins/python-build/README.md#building-for-maximum-performance
            PYTHON_CONFIGURE_OPTS='--enable-optimizations --with-lto' {bin_name()} run :pants-pyenv-install -- 3.10
        """
    )

    default_version = "2.3.13"
    default_url_template = "https://github.com/pyenv/pyenv/archive/refs/tags/v{version}.tar.gz"

    @classproperty
    def default_known_versions(cls):
        return [
            "|".join(
                (
                    cls.default_version,
                    plat,
                    "9105de5e5cf8dc0eca2a520ed04493d183128d46a2cfb402d4cc271af1bf144b",
                    "749323",
                )
            )
            for plat in ["macos_arm64", "macos_x86_64", "linux_x86_64", "linux_arm64"]
        ]

    def generate_exe(self, plat: Platform) -> str:
        """Returns the path to the tool executable.

        If the downloaded artifact is the executable itself, you can leave this unimplemented.

        If the downloaded artifact is an archive, this should be overridden to provide a
        relative path in the downloaded archive, e.g. `./bin/protoc`.
        """
        return f"./pyenv-{self.version}/bin/pyenv"


class PyenvInstallInfoRequest:
    pass


@rule
async def get_pyenv_install_info(
    _: PyenvInstallInfoRequest,
    pyenv_subsystem: PyenvPythonProviderSubsystem,
    platform: Platform,
    python_binary: PythonBinary,
) -> RunRequest:
    env_vars, pyenv = await MultiGet(
        Get(EnvironmentVars, EnvironmentVarsRequest(["PATH"])),
        Get(DownloadedExternalTool, ExternalToolRequest, pyenv_subsystem.get_request(platform)),
    )
    install_script_digest = await Get(
        Digest,
        CreateDigest(
            [
                # NB: We use a bash script for the hot-path to keep overhead minimal, but a Python
                # script for the locking+install to be maximally compatible.
                FileContent(
                    "install_python_shim.sh",
                    dedent(
                        f"""\
                        #!/usr/bin/env bash
                        set -e
                        export PYENV_ROOT=$(readlink {PYENV_NAMED_CACHE})
                        DEST="$PYENV_ROOT"/versions/$1
                        if [ ! -f "$DEST"/DONE ]; then
                            mkdir -p "$DEST" 2>/dev/null || true
                            {python_binary.path} install_python_shim.py $1
                        fi
                        echo "$DEST"/bin/python
                        """
                    ).encode(),
                    is_executable=True,
                ),
                FileContent(
                    "install_python_shim.py",
                    dedent(
                        f"""\
                        import fcntl
                        import pathlib
                        import subprocess
                        import sys

                        PYENV_ROOT = pathlib.Path("{PYENV_NAMED_CACHE}").resolve()
                        SPECIFIC_VERSION = sys.argv[1]
                        SPECIFIC_VERSION_PATH = PYENV_ROOT / "versions" / SPECIFIC_VERSION
                        DONEFILE_PATH = SPECIFIC_VERSION_PATH / "DONE"
                        DONEFILE_LOCK_PATH = SPECIFIC_VERSION_PATH / "DONE.lock"
                        DONEFILE_LOCK_FD = DONEFILE_LOCK_PATH.open(mode="w")

                        def main():
                            if DONEFILE_PATH.exists():
                                return
                            fcntl.lockf(DONEFILE_LOCK_FD, fcntl.LOCK_EX)
                            # Use double-checked locking to ensure that we really need to do the work
                            if DONEFILE_PATH.exists():
                                return

                            subprocess.run(["{pyenv.exe}", "install", SPECIFIC_VERSION], check=True)
                            # Removing write perms helps ensure users aren't accidentally modifying
                            # Python or the site-packages
                            subprocess.run(["chmod", "-R", "-w", str(SPECIFIC_VERSION_PATH)], check=True)
                            subprocess.run(["chmod", "+w", str(SPECIFIC_VERSION_PATH)], check=True)
                            DONEFILE_PATH.touch()

                        if __name__ == "__main__":
                            main()
                        """
                    ).encode(),
                    is_executable=True,
                ),
            ]
        ),
    )

    digest = await Get(Digest, MergeDigests([install_script_digest, pyenv.digest]))
    return RunRequest(
        digest=digest,
        args=["./install_python_shim.sh"],
        extra_env={
            "PATH": env_vars.get("PATH", ""),
            "TMPDIR": "{chroot}/tmpdir",
        },
        append_only_caches=PYENV_APPEND_ONLY_CACHES,
    )


class PyenvPythonProvider(PythonProvider):
    pass


@rule
async def get_python(
    request: PyenvPythonProvider,
    python_setup: PythonSetup,
    platform: Platform,
    pyenv_subsystem: PyenvPythonProviderSubsystem,
) -> PythonExecutable:
    env_vars, pyenv, pyenv_install = await MultiGet(
        Get(EnvironmentVars, EnvironmentVarsRequest(["PATH"])),
        Get(DownloadedExternalTool, ExternalToolRequest, pyenv_subsystem.get_request(platform)),
        Get(RunRequest, PyenvInstallInfoRequest()),
    )

    python_to_use = request.interpreter_constraints.minimum_python_version(
        python_setup.interpreter_versions_universe
    )
    if python_to_use is None:
        raise ValueError(
            f"Couldn't determine a compatible Interpreter Constraint from {python_setup.interpreter_versions_universe}"
        )

    which_python_result = await Get(
        ProcessResult,
        Process(
            [pyenv.exe, "latest", "--known", python_to_use],
            input_digest=pyenv.digest,
            description=f"Choose specific version for Python {python_to_use}",
            env={"PATH": env_vars.get("PATH", "")},
            # Caching the result is OK, since if the user really needs a different patch,
            # they should list a more precise IC.
        ),
    )
    specific_python = which_python_result.stdout.decode().strip()

    # NB: We don't cache this process at any level for two reasons:
    #   1. Several tools (including pex) refer to Python at an absolute path, so a named cache is
    #   the only way for this to work reasonably well. Since the named cache could be wiped between
    #   runs (technically during a run, but we can't do anything about that) the
    #   fastest-yet-still-correct solution is to always run this process and make it bail
    #   early-and-quickly if the requisite Python already exists.
    #   2. Pyenv compiles Python using whatever compiler the system is configured to use. Python
    #   then stores this information so that it can use the same compiler when compiling extension
    #   modules. Therefore caching the compiled Python is somewhat unsafe (especially for a remote
    #   cache). See also https://github.com/pantsbuild/pants/issues/10769.
    result = await Get(
        ProcessResult,
        Process(
            pyenv_install.args + (specific_python,),
            input_digest=pyenv_install.digest,
            description=f"Install Python {python_to_use}",
            append_only_caches=pyenv_install.append_only_caches,
            env=pyenv_install.extra_env,
            # Don't cache, we want this to always be run so that we can assume for the rest of the
            # session the named_cache destination for this Python is valid, as the Python ecosystem
            # mainly assumes absolute paths for Python interpreters.
            cache_scope=ProcessCacheScope.PER_SESSION,
        ),
    )

    return PythonExecutable(
        path=result.stdout.decode().splitlines()[-1].strip(),
        fingerprint=None,
        append_only_caches=PYENV_APPEND_ONLY_CACHES,
    )


@dataclass(frozen=True)
class SyntheticPyenvTargetsRequest(SyntheticTargetsRequest):
    path: str = SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS


@rule
async def make_synthetic_targets(request: SyntheticPyenvTargetsRequest) -> SyntheticAddressMaps:
    return SyntheticAddressMaps.for_targets_request(
        request, [("BUILD.pyenv", (TargetAdaptor("_pyenv_install", "pants-pyenv-install"),))]
    )


@dataclass(frozen=True)
class RunPyenvInstallFieldSet(RunFieldSet):
    run_in_sandbox_behavior = RunInSandboxBehavior.NOT_SUPPORTED
    required_fields = (PyenvInstallSentinelField,)

    _sentinel: PyenvInstallSentinelField


@rule
async def run_pyenv_install(
    _: RunPyenvInstallFieldSet,
    platform: Platform,
    pyenv_subsystem: PyenvPythonProviderSubsystem,
) -> RunRequest:
    run_request, pyenv = await MultiGet(
        Get(RunRequest, PyenvInstallInfoRequest()),
        Get(DownloadedExternalTool, ExternalToolRequest, pyenv_subsystem.get_request(platform)),
    )

    wrapper_script_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    "run_install_python_shim.sh",
                    dedent(
                        f"""\
                        #!/usr/bin/env bash
                        set -e
                        cd "$CHROOT"
                        SPECIFIC_VERSION=$("{pyenv.exe}" latest --known $1)
                        {" ".join(run_request.args)} $SPECIFIC_VERSION
                        """
                    ).encode(),
                    is_executable=True,
                )
            ]
        ),
    )
    digest = await Get(Digest, MergeDigests([run_request.digest, wrapper_script_digest]))
    return dataclasses.replace(
        run_request,
        args=("{chroot}/run_install_python_shim.sh",),
        digest=digest,
        extra_env=FrozenDict(
            {
                "CHROOT": "{chroot}",
                **run_request.extra_env,
            }
        ),
    )


def rules():
    return (
        *collect_rules(),
        *pex_rules(),
        *external_tools_rules(),
        *RunPyenvInstallFieldSet.rules(),
        UnionRule(PythonProvider, PyenvPythonProvider),
        UnionRule(SyntheticTargetsRequest, SyntheticPyenvTargetsRequest),
    )
