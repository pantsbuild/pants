# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import importlib
import locale
import os
import sys
import time
import warnings

from pants.base.exiter import PANTS_FAILED_EXIT_CODE
from pants.bin.pants_env_vars import (
    DAEMON_ENTRYPOINT,
    IGNORE_UNRECOGNIZED_ENCODING,
    RECURSION_LIMIT,
)
from pants.bin.pants_runner import PantsRunner
from pants.engine.internals import native_engine
from pants.util.strutil import softwrap


class PantsLoader:
    """Initial entrypoint for pants.

    Executes a pants_runner by default, or executes a pantsd-specific entrypoint.
    """

    @staticmethod
    def setup_warnings() -> None:
        # We want to present warnings to the user, set this up before importing any of our own code,
        # to ensure all deprecation warnings are seen, including module deprecations.
        # The "default" action displays a warning for a particular file and line number exactly once.
        # See https://docs.python.org/3/library/warnings.html#the-warnings-filter for the complete list.
        #
        # However, we do turn off deprecation warnings for libraries that Pants uses for which we do
        # not have a fixed upstream version, typically because the library is no longer maintained.
        warnings.simplefilter("default", category=DeprecationWarning)
        # TODO: Eric-Arellano has emailed the author to see if he is willing to accept a PR fixing the
        # deprecation warnings and to release the fix. If he says yes, remove this once fixed.
        warnings.filterwarnings("ignore", category=DeprecationWarning, module="ansicolors")
        # Silence ctypes _pack_/_layout_ warning from HdrHistogram; due by Python 3.19
        # See: https://github.com/HdrHistogram/HdrHistogram/issues/216
        warnings.filterwarnings(
            "ignore",
            category=DeprecationWarning,
            message=r"Due to '_pack_', the '.+' Structure will use memory layout compatible with MSVC",
        )
        # Silence this ubiquitous warning. Several of our 3rd party deps incur this.
        warnings.filterwarnings(
            "ignore",
            category=DeprecationWarning,
            message="Using or importing the ABCs from 'collections' instead of from 'collections.abc' is deprecated",
        )

    @classmethod
    def ensure_locale(cls) -> None:
        """Ensure the locale uses UTF-8 encoding, or prompt for an explicit bypass."""

        encoding = locale.getpreferredencoding()
        if (
            encoding.lower() != "utf-8"
            and os.environ.get(IGNORE_UNRECOGNIZED_ENCODING, None) is None
        ):
            raise RuntimeError(
                softwrap(
                    f"""
                    Your system's preferred encoding is `{encoding}`, but Pants requires `UTF-8`.
                    Specifically, Python's `locale.getpreferredencoding()` must resolve to `UTF-8`.

                    You can fix this by setting the LC_* and LANG environment variables, e.g.:
                      LC_ALL=en_US.UTF-8
                      LANG=en_US.UTF-8
                    Or, bypass it by setting {IGNORE_UNRECOGNIZED_ENCODING}=1. Note that
                    pants may exhibit inconsistent behavior if this check is bypassed.
                    """
                )
            )

    @staticmethod
    def sandboxer_bin() -> str | None:
        # In theory as_file could return a temporary file and clean it up, so we'd be returning
        # an invalid path. But in practice we know that we're running either in a venv with all
        # resources expanded on disk, or from sources, and either way we will get a persistent
        # valid path that will not be cleaned up.
        with importlib.resources.as_file(
            importlib.resources.files("pants.bin").joinpath("sandboxer")
        ) as sandboxer_bin:
            if os.path.isfile(sandboxer_bin):
                os.chmod(sandboxer_bin, 0o755)
                return str(sandboxer_bin)
        return None

    @staticmethod
    def run_alternate_entrypoint(entrypoint: str) -> None:
        try:
            module_path, func_name = entrypoint.split(":", 1)
        except ValueError:
            print(
                f"{DAEMON_ENTRYPOINT} must be of the form `module.path:callable`", file=sys.stderr
            )
            sys.exit(PANTS_FAILED_EXIT_CODE)

        module = importlib.import_module(module_path)
        entrypoint_fn = getattr(module, func_name)
        entrypoint_fn()

    @staticmethod
    def run_default_entrypoint() -> None:
        start_time = time.time()
        try:
            runner = PantsRunner(args=sys.argv, env=os.environ)
            exit_code = runner.run(start_time)
        except KeyboardInterrupt as e:
            print(f"Interrupted by user:\n{e}", file=sys.stderr)
            exit_code = PANTS_FAILED_EXIT_CODE
        sys.exit(exit_code)

    @classmethod
    def main(cls) -> None:
        native_engine.initialize()
        cls.setup_warnings()
        cls.ensure_locale()

        sys.setrecursionlimit(int(os.environ.get(RECURSION_LIMIT, "10000")))

        os.environ["PANTS_SANDBOXER_BINARY_PATH"] = cls.sandboxer_bin() or ""
        entrypoint = os.environ.pop(DAEMON_ENTRYPOINT, None)
        if entrypoint:
            cls.run_alternate_entrypoint(entrypoint)
        else:
            cls.run_default_entrypoint()


def main() -> None:
    PantsLoader.main()


if __name__ == "__main__":
    main()
