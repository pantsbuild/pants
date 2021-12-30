# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: This only exists to resolve a circular import that will be fixed in Pants 2.10.
from __future__ import annotations

from textwrap import dedent

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules.pex_environment import PexRuntimeEnvironment
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import BinaryNotFoundError, BinaryPathRequest, BinaryPaths, BinaryPathTest
from pants.engine.rules import collect_rules, rule
from pants.python.binaries import PythonBinary, PythonBootstrap
from pants.util.logging import LogLevel


@rule(desc="Finding a `python` binary", level=LogLevel.TRACE)
async def find_python(
    python_bootstrap: PythonBootstrap,
    python_setup: PythonSetup,
    pex_runtime_environment: PexRuntimeEnvironment,
) -> PythonBinary:

    # PEX files are compatible with bootstrapping via Python 2.7 or Python 3.5+, but we select 3.6+
    # for maximum compatibility with internal scripts.
    interpreter_search_paths = python_bootstrap.interpreter_search_paths(python_setup)
    all_python_binary_paths = await MultiGet(
        Get(
            BinaryPaths,
            BinaryPathRequest(
                search_path=interpreter_search_paths,
                binary_name=binary_name,
                check_file_entries=True,
                test=BinaryPathTest(
                    args=[
                        "-c",
                        # N.B.: The following code snippet must be compatible with Python 3.6+.
                        #
                        # We hash the underlying Python interpreter executable to ensure we detect
                        # changes in the real interpreter that might otherwise be masked by Pyenv
                        # shim scripts found on the search path. Naively, just printing out the full
                        # version_info would be enough, but that does not account for supported abi
                        # changes (e.g.: a pyenv switch from a py27mu interpreter to a py27m
                        # interpreter.)
                        #
                        # When hashing, we pick 8192 for efficiency of reads and fingerprint updates
                        # (writes) since it's a common OS buffer size and an even multiple of the
                        # hash block size.
                        dedent(
                            """\
                            import sys

                            major, minor = sys.version_info[:2]
                            if not (major == 3 and minor >= 6):
                                sys.exit(1)

                            import hashlib
                            hasher = hashlib.sha256()
                            with open(sys.executable, "rb") as fp:
                                for chunk in iter(lambda: fp.read(8192), b""):
                                    hasher.update(chunk)
                            sys.stdout.write(hasher.hexdigest())
                            """
                        ),
                    ],
                    fingerprint_stdout=False,  # We already emit a usable fingerprint to stdout.
                ),
            ),
        )
        for binary_name in python_bootstrap.interpreter_names(pex_runtime_environment)
    )

    for binary_paths in all_python_binary_paths:
        path = binary_paths.first_path
        if path:
            return PythonBinary(
                path=path.path,
                fingerprint=path.fingerprint,
            )

    raise BinaryNotFoundError(
        "Was not able to locate a Python interpreter to execute rule code.\n"
        "Please ensure that Python is available in one of the locations identified by "
        "`[python-bootstrap] search_path`, which currently expands to:\n"
        f"  {interpreter_search_paths}"
    )


def rules():
    return collect_rules()
