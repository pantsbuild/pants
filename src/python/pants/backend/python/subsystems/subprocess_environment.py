# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Dict, Optional

from pants.engine.rules import rule, subsystem_rule
from pants.subsystem.subsystem import Subsystem


class SubprocessEnvironment(Subsystem):
    options_scope = "subprocess-environment"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        # TODO(#7735): move the --lang and --lc-all flags to a general subprocess support subystem.
        register(
            "--lang",
            default=os.environ.get("LANG"),
            fingerprint=True,
            advanced=True,
            help="Override the `LANG` environment variable for any forked subprocesses.",
        )
        register(
            "--lc-all",
            default=os.environ.get("LC_ALL"),
            fingerprint=True,
            advanced=True,
            help="Override the `LC_ALL` environment variable for any forked subprocesses.",
        )


@dataclass(frozen=True)
class SubprocessEncodingEnvironment:
    lang: Optional[str]
    lc_all: Optional[str]

    @property
    def invocation_environment_dict(self) -> Dict[str, str]:
        return {
            "LANG": self.lang or "",
            "LC_ALL": self.lc_all or "",
        }


@rule
def create_subprocess_encoding_environment(
    subprocess_environment: SubprocessEnvironment,
) -> SubprocessEncodingEnvironment:
    return SubprocessEncodingEnvironment(
        lang=subprocess_environment.get_options().lang,
        lc_all=subprocess_environment.get_options().lc_all,
    )


def rules():
    return [
        subsystem_rule(SubprocessEnvironment),
        create_subprocess_encoding_environment,
    ]
