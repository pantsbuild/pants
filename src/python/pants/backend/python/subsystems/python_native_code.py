# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Dict, Tuple

from pants.engine.rules import collect_rules
from pants.option.subsystem import Subsystem
from pants.util.strutil import safe_shlex_join, safe_shlex_split


class PythonNativeCode(Subsystem):
    """Options for building native code using Python, e.g. when resolving distributions."""

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

    @property
    def cpp_flags(self) -> Tuple[str, ...]:
        return tuple(self.options.cpp_flags)

    @property
    def ld_flags(self) -> Tuple[str, ...]:
        return tuple(self.options.ld_flags)

    @property
    def environment_dict(self) -> Dict[str, str]:
        return {
            "CPPFLAGS": safe_shlex_join(self.cpp_flags),
            "LDFLAGS": safe_shlex_join(self.ld_flags),
        }


def rules():
    return collect_rules()
