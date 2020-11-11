# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import locale
import os
import warnings
from textwrap import dedent


class PantsLoader:
    """Loads and executes entrypoints."""

    ENTRYPOINT_ENV_VAR = "PANTS_ENTRYPOINT"
    DEFAULT_ENTRYPOINT = "pants.bin.pants_exe:main"

    ENCODING_IGNORE_ENV_VAR = "PANTS_IGNORE_UNRECOGNIZED_ENCODING"

    class InvalidLocaleError(Exception):
        """Raised when a valid locale can't be found."""

    @staticmethod
    def setup_warnings():
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
    def ensure_locale(cls):
        # Sanity check for locale, See https://github.com/pantsbuild/pants/issues/2465.
        # This check is done early to give good feedback to user on how to fix the problem. Other
        # libraries called by Pants may fail with more obscure errors.
        encoding = locale.getpreferredencoding()
        if (
            encoding.lower() != "utf-8"
            and os.environ.get(cls.ENCODING_IGNORE_ENV_VAR, None) is None
        ):
            raise cls.InvalidLocaleError(
                dedent(
                    """
                    Your system's preferred encoding is `{}`, but Pants requires `UTF-8`.
                    Specifically, Python's `locale.getpreferredencoding()` must resolve to `UTF-8`.

                    Fix it by setting the LC_* and LANG environment settings. Example:
                      LC_ALL=en_US.UTF-8
                      LANG=en_US.UTF-8
                    Or, bypass it by setting the below environment variable.
                      {}=1
                    Note: we cannot guarantee consistent behavior with this bypass enabled.
                    """.format(
                        encoding, cls.ENCODING_IGNORE_ENV_VAR
                    )
                )
            )

    @staticmethod
    def determine_entrypoint(env_var, default):
        return os.environ.pop(env_var, default)

    @staticmethod
    def load_and_execute(entrypoint):
        assert ":" in entrypoint, "ERROR: entrypoint must be of the form `module.path:callable`"
        module_path, func_name = entrypoint.split(":", 1)
        module = importlib.import_module(module_path)
        entrypoint_main = getattr(module, func_name)
        assert callable(entrypoint_main), "ERROR: entrypoint `{}` is not callable".format(
            entrypoint
        )
        entrypoint_main()

    @classmethod
    def run(cls):
        cls.setup_warnings()
        cls.ensure_locale()
        entrypoint = cls.determine_entrypoint(cls.ENTRYPOINT_ENV_VAR, cls.DEFAULT_ENTRYPOINT)
        cls.load_and_execute(entrypoint)


def main():
    PantsLoader.run()


if __name__ == "__main__":
    main()
