# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Dict

from pants.engine.rules import collect_rules
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import safe_shlex_join, safe_shlex_split


class PythonNativeCode(Subsystem):
    options_scope = "python-native-code"
    help = "Options for building native code using Python, e.g. when resolving distributions."

    # TODO(#7735): move the --cpp-flags and --ld-flags to a general subprocess support subsystem.
    cpp_flags = StrListOption(
        default=safe_shlex_split(os.environ.get("CPPFLAGS", "")),
        help="Override the `CPPFLAGS` environment variable for any forked subprocesses.",
        advanced=True,
    )
    ld_flags = StrListOption(
        default=safe_shlex_split(os.environ.get("LDFLAGS", "")),
        help="Override the `LDFLAGS` environment variable for any forked subprocesses.",
        advanced=True,
    )

    @property
    def environment_dict(self) -> Dict[str, str]:
        return {
            "CPPFLAGS": safe_shlex_join(self.cpp_flags),
            "LDFLAGS": safe_shlex_join(self.ld_flags),
        }


def rules():
    return collect_rules()
