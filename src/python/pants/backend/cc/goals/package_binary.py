# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# from __future__ import annotations

# import logging

# from pants.backend.cc.subsystems.toolchain import CCToolchain
# from pants.backend.cc.target_types import CCBinaryFieldSet
# from pants.core.goals.package import BuiltPackage
# from pants.engine.rules import rule
# from pants.util.logging import LogLevel

# logger = logging.getLogger(__name__)


# @rule(level=LogLevel.DEBUG)
# async def package_cc_binary(
#     toolchain: CCToolchain,
#     field_set: CCBinaryFieldSet,
# ) -> BuiltPackage:
#     pass
