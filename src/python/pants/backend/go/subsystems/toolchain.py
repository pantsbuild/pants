# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.external_tool import ExternalToolError, ExternalToolVersion
from pants.engine.platform import Platform
from pants.option.option_types import BoolOption, StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class GoToolchain(Subsystem):
    options_scope = "go-toolchain"
    help = "Options for the Go toolchain provider."

    enabled = BoolOption(
        default=True,
        help=softwrap(
            """
            If true, Pants will provide a Go distribution instead of requiring one to be installed on the host system.
            """
        ),
    )

    known_versions = StrListOption(
        default=[
            "1.21.6|linux_arm64|e2e8aa88e1b5170a0d495d7d9c766af2b2b6c6925a8f8956d834ad6b4cacbd9a|63801908",
            "1.21.6|linux_x86_64|3f934f40ac360b9c01f616a9aa1796d227d8b0328bf64cb045c7b8c4ee9caea4|66704768",
            "1.21.6|macos_arm64|0ff541fb37c38e5e5c5bcecc8f4f43c5ffd5e3a6c33a5d3e4003ded66fcfb331|65181002",
            "1.21.6|macos_x86_64|31d6ecca09010ab351e51343a5af81d678902061fee871f912bdd5ef4d77885|67393530",
        ],
        help=softwrap(
            """
            A list of known Go versions, in the format:
            `<version>|<platform>|<sha256>|<size_in_bytes>`.
            """
        ),
    )
    version = StrOption(
        default="1.21.6",
        help=softwrap(
            """
            The version of Go to use.
            """
        ),
    )

    @classmethod
    def decode_known_version(cls, known_version: str) -> ExternalToolVersion:
        try:
            return ExternalToolVersion.decode(known_version)
        except ValueError:
            raise ExternalToolError(
                f"Bad value for [{cls.options_scope}].known_versions: {known_version}"
            )

    def known_version(self, plat: Platform) -> ExternalToolVersion | None:
        for known_version in self.known_versions:
            tool_version = self.decode_known_version(known_version)
            if plat.value == tool_version.platform and tool_version.version == self.version:
                return tool_version
        return None
