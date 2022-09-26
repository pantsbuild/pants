# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Sequence

from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import safe_shlex_join, safe_shlex_split


class PythonNativeCodeSubsystem(Subsystem):
    options_scope = "python-native-code"
    help = "Options for building native code using Python, e.g. when resolving distributions."

    class EnvironmentAware(Subsystem.EnvironmentAware):
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


@dataclass(frozen=True)
class PythonNativeCodeEnvironment:

    cpp_flags: tuple[str, ...]
    ld_flags: tuple[str, ...]

    @property
    def environment_dict(self) -> Dict[str, str]:
        return {
            "CPPFLAGS": safe_shlex_join(self.cpp_flags),
            "LDFLAGS": safe_shlex_join(self.ld_flags),
        }


@rule
async def resolve_python_native_code_environment(
    env_aware: PythonNativeCodeSubsystem.EnvironmentAware,
) -> PythonNativeCodeEnvironment:

    env_vars = await Get(EnvironmentVars, EnvironmentVarsRequest(("CPPFLAGS", "LDFLAGS")))

    def iter_values(env_var: str, values: Sequence[str]):
        for value in values:
            if value == f"<{env_var}>":
                yield from safe_shlex_split(env_vars.get(env_var, ""))
            else:
                yield value

    return PythonNativeCodeEnvironment(
        cpp_flags=tuple(iter_values("CPPFLAGS", env_aware._cpp_flags)),
        ld_flags=tuple(iter_values("LDFLAGS", env_aware._ld_flags)),
    )


def rules():
    return [*collect_rules()]
