# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Analyze contents of nfpm-generated system packages to auto-generate deps from native lib deps.
"""

from pants.backend.nfpm.native_libs.rules import rules as native_libs_rules


# def target_types():
#     return native_libs_target_types()


def rules():
    return [
        *native_libs_rules(),
    ]
