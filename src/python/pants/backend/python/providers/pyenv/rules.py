# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent  # noqa: PNT20

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules.pex import PythonProvider
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.core.goals.run import RunRequest
from pants.core.util_rules.adhoc_binaries import PythonBuildStandaloneBinary
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.core.util_rules.external_tool import rules as external_tools_rules
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import StrListOption
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.strutil import softwrap, stable_hash

PYENV_NAMED_CACHE = ".pyenv"
PYENV_APPEND_ONLY_CACHES = FrozenDict({"pyenv": PYENV_NAMED_CACHE})


class PyenvPythonProviderSubsystem(TemplatedExternalTool):
    options_scope = "pyenv-python-provider"
    name = "pyenv"
    help = softwrap(
        """
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
        """
    )

    default_version = "2.4.7"
    default_url_template = "https://github.com/pyenv/pyenv/archive/refs/tags/v{version}.tar.gz"

    class EnvironmentAware:
        installation_extra_env_vars = StrListOption(
            help=softwrap(
                """
                Additional environment variables to include when running `pyenv install`.

                Entries are strings in the form `ENV_VAR=value` to use explicitly; or just
                `ENV_VAR` to copy the value of a variable in Pants's own environment.

                This is especially useful if you want to use an optimized Python (E.g. setting
                `PYTHON_CONFIGURE_OPTS='--enable-optimizations --with-lto'` and
                `PYTHON_CFLAGS='-march=native -mtune=native'`) or need custom compiler flags.

                Note that changes to this option result in a different fingerprint for the installed
                Python, and therefore will cause a full re-install if changed.

                See https://github.com/pyenv/pyenv/blob/master/plugins/python-build/README.md#special-environment-variables
                for supported env vars.
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
                    "0c0137963dd3c4b356663a3a152a64815e5e4364f131f2976a2731a13ab1de4d",
                    "799490",
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
    pyenv_env_aware: PyenvPythonProviderSubsystem.EnvironmentAware,
    platform: Platform,
    bootstrap_python: PythonBuildStandaloneBinary,
) -> RunRequest:
    env_vars, pyenv = await MultiGet(
        Get(
            EnvironmentVars,
            EnvironmentVarsRequest(("PATH",) + pyenv_env_aware.installation_extra_env_vars),
        ),
        Get(DownloadedExternalTool, ExternalToolRequest, pyenv_subsystem.get_request(platform)),
    )
    installation_env_vars = {key: name for key, name in env_vars.items() if key != "PATH"}
    installation_fingerprint = stable_hash(installation_env_vars)
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
                        export PYENV_ROOT=$(readlink {PYENV_NAMED_CACHE})/{installation_fingerprint}
                        DEST="$PYENV_ROOT"/versions/$1
                        if [ ! -f "$DEST"/DONE ]; then
                            mkdir -p "$DEST" 2>/dev/null || true
                            {bootstrap_python.path} install_python_shim.py $1
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
                        import shutil
                        import subprocess
                        import sys

                        PYENV_ROOT = pathlib.Path("{PYENV_NAMED_CACHE}", "{installation_fingerprint}").resolve()
                        SPECIFIC_VERSION = sys.argv[1]
                        SPECIFIC_VERSION_PATH = PYENV_ROOT / "versions" / SPECIFIC_VERSION

                        # NB: We put the "DONE" file inside the specific version destination so that
                        # users can wipe the directory clean and expect Pants to re-install that version.
                        DONEFILE_PATH = SPECIFIC_VERSION_PATH / "DONE"

                        def main():
                            if DONEFILE_PATH.exists():
                                return

                            lockfile_fd = SPECIFIC_VERSION_PATH.with_suffix(".lock").open(mode="w")
                            fcntl.lockf(lockfile_fd, fcntl.LOCK_EX)
                            # Use double-checked locking to ensure that we really need to do the work
                            if DONEFILE_PATH.exists():
                                return

                            # If a previous install failed this directory may exist in an intermediate
                            # state, and pyenv may choke trying to install into it, so we remove it.
                            shutil.rmtree(SPECIFIC_VERSION_PATH, ignore_errors=True)

                            subprocess.run(["{pyenv.exe}", "install", SPECIFIC_VERSION], check=True)
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
            **installation_env_vars,
        },
        append_only_caches={**PYENV_APPEND_ONLY_CACHES, **bootstrap_python.APPEND_ONLY_CACHES},
    )


class PyenvPythonProvider(PythonProvider):
    pass


def _major_minor_patch_to_int(major_minor_patch: str) -> tuple[int, int, int]:
    major, minor, patch = map(int, major_minor_patch.split(".", maxsplit=2))
    return (major, minor, patch)


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

    # Determine the lowest major/minor version supported according to the interpreter constraints.
    major_minor_to_use_str = request.interpreter_constraints.minimum_python_version(
        python_setup.interpreter_versions_universe
    )
    if major_minor_to_use_str is None:
        raise ValueError(
            f"Couldn't determine a compatible Interpreter Constraint from {python_setup.interpreter_versions_universe}"
        )

    # Find the highest patch version given the major/minor version that is known to our version of pyenv.
    pyenv_latest_known_result = await Get(
        ProcessResult,
        Process(
            [pyenv.exe, "latest", "--known", major_minor_to_use_str],
            input_digest=pyenv.digest,
            description=f"Choose specific version for Python {major_minor_to_use_str}",
            env={"PATH": env_vars.get("PATH", "")},
        ),
    )
    major_to_use, minor_to_use, latest_known_patch = _major_minor_patch_to_int(
        pyenv_latest_known_result.stdout.decode().strip()
    )

    # Pick the highest patch version given the major/minor version that is supported according to
    # the interpreter constraints and known to our version of pyenv.
    # We assume pyenv knows every patch version smaller or equal the its latest known patch
    # version, to avoid calling it for each patch version separately.
    supported_triplets = request.interpreter_constraints.enumerate_python_versions(
        python_setup.interpreter_versions_universe
    )
    try:
        major_minor_patch_to_use = max(
            (major, minor, patch)
            for (major, minor, patch) in supported_triplets
            if major == major_to_use and minor == minor_to_use and patch <= latest_known_patch
        )
    except ValueError:
        raise ValueError(
            f"Couldn't find a Python {major_minor_to_use_str} version that"
            f" is compatible with the interpreter constraints {request.interpreter_constraints}"
            f" and known to pyenv {pyenv_subsystem.version}"
            f" (latest known version {major_to_use}.{minor_to_use}.{latest_known_patch})."
            " Suggestion: consider upgrading pyenv or adjusting your interpreter constraints."
        ) from None

    major_minor_patch_to_use_str = ".".join(map(str, major_minor_patch_to_use))

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
            pyenv_install.args + (major_minor_patch_to_use_str,),
            level=LogLevel.DEBUG,
            input_digest=pyenv_install.digest,
            description=f"Install Python {major_minor_patch_to_use_str}",
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


def rules():
    return (
        *collect_rules(),
        *pex_rules(),
        *external_tools_rules(),
        UnionRule(PythonProvider, PyenvPythonProvider),
    )
