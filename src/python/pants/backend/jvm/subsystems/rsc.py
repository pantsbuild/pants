# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.subsystems.zinc import _ZINC_COMPILER_VERSION
from pants.binaries.binary_tool import NativeTool
from pants.util.memo import memoized_method


class Rsc(NativeTool):
    options_scope = "rsc"

    default_version = _ZINC_COMPILER_VERSION
    name = "rsc-pants-native-image"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--native-image",
            fingerprint=True,
            type=bool,
            help="Use a pre-compiled native-image for rsc. Requires running in hermetic mode",
        )
        register(
            "--jvm-options",
            type=list,
            metavar="<option>...",
            help="Run RSC with these jvm options.",
        )

    @property
    def use_native_image(self):
        return self.get_options().native_image

    @memoized_method
    def native_image(self, context):
        return self.hackily_snapshot(context)
