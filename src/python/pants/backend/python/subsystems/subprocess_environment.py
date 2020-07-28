# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Dict, Optional, cast

from pants.engine.rules import collect_rules
from pants.subsystem.subsystem import Subsystem


class SubprocessEnvironment(Subsystem):
    """Environment for forked subprocesses."""

    options_scope = "subprocess-environment"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        # TODO(#7735): move the --lang and --lc-all flags to a general subprocess support subsystem.
        register(
            "--lang",
            type=str,
            default=os.environ.get("LANG"),
            advanced=True,
            help="Override the `LANG` environment variable for any forked subprocesses.",
        )
        register(
            "--lc-all",
            type=str,
            default=os.environ.get("LC_ALL"),
            advanced=True,
            help="Override the `LC_ALL` environment variable for any forked subprocesses.",
        )

    @property
    def lang(self) -> Optional[str]:
        return cast(Optional[str], self.options.lang)

    @property
    def lc_all(self) -> Optional[str]:
        return cast(Optional[str], self.options.lc_all)

    @property
    def invocation_environment(self) -> Dict[str, str]:
        return {"LANG": self.lang or "", "LC_ALL": self.lc_all or ""}


def rules():
    return collect_rules()
