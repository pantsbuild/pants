# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.backend.codegen.protobuf.buf import Buf as ParentBuf
from pants.option.custom_types import shell_str
from pants.util.docutil import bin_name


class Buf(ParentBuf):
    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=f"Don't use Buf when running `{bin_name()} lint`.",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=("Arguments to pass directly to Buf, e.g. `--buf-args='--error-format json'`.'"),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> tuple[str, ...]:
        return tuple(self.options.args)
