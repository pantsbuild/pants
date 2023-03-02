# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent  # noqa: PNT20

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules.pex import PythonProvider
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex_environment import PythonExecutable
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
from pants.util.meta import classproperty


class PyenvSubsystem(TemplatedExternalTool):
    options_scope = "pyenv"
    name = "pyenv"
    help = "pyenv (https://github.com/pyenv/pyenv)."

    default_version = "2.3.13"
    default_url_template = "https://github.com/pyenv/pyenv/archive/refs/tags/v{version}.tar.gz"

    python_configure_opts = StrListOption(
        help="Flags to use when configuring CPython.",
        advanced=True,
    )

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


class PyenvPythonProvider(PythonProvider):
    pass


PYENV_NAMED_CACHE = ".pyenv"
PYENV_APPEND_ONLY_CACHES = FrozenDict({"pyenv": PYENV_NAMED_CACHE})


@rule
async def get_python(
    request: PyenvPythonProvider,
    python_setup: PythonSetup,
    platform: Platform,
    pyenv_subsystem: PyenvSubsystem,
) -> PythonExecutable:
    env_vars, pyenv = await MultiGet(
        Get(EnvironmentVars, EnvironmentVarsRequest(["PATH", "LDFLAGS"])),
        Get(DownloadedExternalTool, ExternalToolRequest, pyenv_subsystem.get_request(platform)),
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

    shim_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    "install_python_shim.sh",
                    dedent(
                        f"""\
                        #!/usr/bin/env bash
                        set -e
                        DEST=.pyenv/versions/3.7.16
                        while [ ! -f $DEST/DONE ]; do
                            LOCKFILE=$DEST/DONE.lock
                            mkdir -p $DEST 2>/dev/null || true
                            TMPLOCK=$(mktemp -p $DEST DONE.lock.XXXX)
                            if ln $TMPLOCK $LOCKFILE 2>/dev/null ; then
                                trap 'rm -f $LOCKFILE' EXIT
                                export PYENV_ROOT=.pyenv
                                ./pyenv-2.3.13/bin/pyenv install 3.7.16
                                # Removing write perms helps ensure users aren't accidentally modifying Python
                                # or the site-packages
                                chmod -R -w $DEST
                                chmod +w $DEST
                                touch $DEST/DONE
                            else
                                sleep 1
                            fi
                            rm -f $TMPLOCK
                        done
                        echo $(realpath $DEST/bin/python)
                        """
                    ).encode(),
                    is_executable=True,
                )
            ]
        ),
    )
    digest = await Get(Digest, MergeDigests([shim_digest, pyenv.digest]))

    # NB: We don't cache this process at any level for two reasons:
    #   1. Several tools (including pex) refer to Python at an absolute path, so a named cache is
    #   the only way for this to work reasonably well. Since the named cache could be wiped between
    #   runs (technically during a run, but we can't do anything about that) the
    #   fastest-yet-still-correct solution is to always run this process and make it bail
    #   early-and-quickly if the requisite Python already exists.
    #   2. Pyenv compiles Python using whatever compiler the system is configured to use. Python
    #   then stores this information so that it can use the same compiler when compiling extension
    #   modules. Therefore caching the compiled Python is somewhat unsafe (especially for a remote
    #   cache).
    result = await Get(
        ProcessResult,
        Process(
            ["./install_python_shim.sh"],
            input_digest=digest,
            description=f"Install Python {python_to_use}",
            append_only_caches=PYENV_APPEND_ONLY_CACHES,
            env={
                "PATH": env_vars.get("PATH", ""),
                "TMPDIR": "{chroot}/tmpdir",
                "LDFLAGS": env_vars.get("LDFLAGS", ""),
                "PYTHON_CONFIGURE_OPTS": " ".join(pyenv_subsystem.python_configure_opts),
            },
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
