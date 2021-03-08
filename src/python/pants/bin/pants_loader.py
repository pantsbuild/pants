# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import locale
import logging
import os
import sys
import time
import warnings
from textwrap import dedent

from pants.base.exiter import PANTS_FAILED_EXIT_CODE
from pants.bin.pants_env_vars import (
    DAEMON_ENTRYPOINT,
    IGNORE_UNRECOGNIZED_ENCODING,
    PANTSC_PROFILE,
    RECURSION_LIMIT,
)
from pants.bin.pants_runner import PantsRunner
from pants.util.contextutil import maybe_profiled


class PantsLoader:
    """Initial entrypoint for pants.

    Executes a pants_runner by default, or executs a pantsd-specific entrypoint.
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
                dedent(
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

        try:
            entrypoint_fn()
        except TypeError:
            print(f"{DAEMON_ENTRYPOINT} {func_name} is not callable", file=sys.stderr)
            sys.exit(PANTS_FAILED_EXIT_CODE)

    @staticmethod
    def run_default_entrypoint() -> None:
        logger = logging.getLogger(__name__)
        with maybe_profiled(os.environ.get(PANTSC_PROFILE)):
            start_time = time.time()
            try:
                runner = PantsRunner(args=sys.argv, env=os.environ)
                exit_code = runner.run(start_time)
            except KeyboardInterrupt as e:
                print(f"Interrupted by user:\n{e}", file=sys.stderr)
                exit_code = PANTS_FAILED_EXIT_CODE
            except Exception as e:
                logger.exception(e)
                exit_code = PANTS_FAILED_EXIT_CODE
        sys.exit(exit_code)

    @classmethod
    def main(cls) -> None:
        cls.setup_warnings()
        cls.ensure_locale()

        sys.setrecursionlimit(int(os.environ.get(RECURSION_LIMIT, "10000")))

        entrypoint = os.environ.pop(DAEMON_ENTRYPOINT, None)

        if entrypoint:
            cls.run_alternate_entrypoint(entrypoint)
        else:
            cls.run_default_entrypoint()


def main() -> None:
    PantsLoader.main()


if __name__ == "__main__":
    main()
