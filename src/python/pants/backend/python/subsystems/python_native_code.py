# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Dict, Tuple

from pants.engine.rules import SubsystemRule, rule
from pants.subsystem.subsystem import Subsystem
from pants.util.strutil import safe_shlex_join, safe_shlex_split


class PythonNativeCode(Subsystem):
    """A subsystem which exposes components of the native backend to the python backend."""

    options_scope = "python-native-code"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        # TODO(#7735): move the --cpp-flags and --ld-flags to a general subprocess support subsystem.
        register(
            "--cpp-flags",
            type=list,
            default=safe_shlex_split(os.environ.get("CPPFLAGS", "")),
            advanced=True,
            help="Override the `CPPFLAGS` environment variable for any forked subprocesses.",
        )
        register(
            "--ld-flags",
            type=list,
            default=safe_shlex_split(os.environ.get("LDFLAGS", "")),
            advanced=True,
            help="Override the `LDFLAGS` environment variable for any forked subprocesses.",
        )


@dataclass(frozen=True)
class PexBuildEnvironment:
    cpp_flags: Tuple[str, ...]
    ld_flags: Tuple[str, ...]

    @property
    def invocation_environment_dict(self) -> Dict[str, str]:
        return {
            "CPPFLAGS": safe_shlex_join(self.cpp_flags),
            "LDFLAGS": safe_shlex_join(self.ld_flags),
        }


@rule
def create_pex_native_build_environment(
    python_native_code: PythonNativeCode,
) -> PexBuildEnvironment:
    return PexBuildEnvironment(
        cpp_flags=python_native_code.get_options().cpp_flags,
        ld_flags=python_native_code.get_options().ld_flags,
    )


def rules():
    return [SubsystemRule(PythonNativeCode), create_pex_native_build_environment]
