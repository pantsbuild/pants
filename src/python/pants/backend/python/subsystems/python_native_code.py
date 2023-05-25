# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Sequence

from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import safe_shlex_join, safe_shlex_split


class PythonNativeCodeSubsystem(Subsystem):
    options_scope = "python-native-code"
    help = "Options for building native code using Python, e.g. when resolving distributions."

    class EnvironmentAware(Subsystem.EnvironmentAware):
        env_vars_used_by_options = ("CPPFLAGS", "LDFLAGS")

        # TODO(#7735): move the --cpp-flags and --ld-flags to a general subprocess support subsystem.
        _cpp_flags = StrListOption(
            default=["<CPPFLAGS>"],
            help=(
                "Override the `CPPFLAGS` environment variable for any forked subprocesses. "
                "Use the value `['<CPPFLAGS>']` to inherit the value of the `CPPFLAGS` "
                "environment variable from your runtime environment target."
            ),
            advanced=True,
        )
        _ld_flags = StrListOption(
            default=["<LDFLAGS>"],
            help=(
                "Override the `LDFLAGS` environment variable for any forked subprocesses. "
                "Use the value `['<LDFLAGS>']` to inherit the value of the `LDFLAGS` environment "
                "variable from your runtime environment target."
            ),
            advanced=True,
        )

        @property
        def subprocess_env_vars(self) -> dict[str, str]:
            return {
                "CPPFLAGS": safe_shlex_join(self._iter_values("CPPFLAGS", self._cpp_flags)),
                "LDFLAGS": safe_shlex_join(self._iter_values("LDFLAGS", self._ld_flags)),
            }

        def _iter_values(self, env_var: str, values: Sequence[str]):
            for value in values:
                if value == f"<{env_var}>":
                    yield from safe_shlex_split(self._options_env.get(env_var, ""))
                else:
                    yield value
