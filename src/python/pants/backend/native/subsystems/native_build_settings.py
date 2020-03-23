# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.build_graph.mirrored_target_option_mixin import MirroredTargetOptionMixin
from pants.subsystem.subsystem import Subsystem


class NativeBuildSettings(Subsystem, MirroredTargetOptionMixin):
    """Settings which affect both the compile and link phases."""

    options_scope = "native-build-settings"

    mirrored_target_option_actions = {
        "strict_deps": lambda tgt: tgt.strict_deps,
    }

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        # TODO: rename this so it's clear it is not the same option as JVM strict deps!
        register(
            "--strict-deps",
            type=bool,
            default=True,
            fingerprint=True,
            advanced=True,
            help="Whether to include only dependencies directly declared in the BUILD file "
            "for C and C++ targets by default. If this is False, all transitive dependencies "
            "are used when compiling and linking native code. C and C++ targets may override "
            "this behavior with the strict_deps keyword argument as well.",
        )

    def get_strict_deps_value_for_target(self, target):
        return self.get_scalar_mirrored_target_option("strict_deps", target)
