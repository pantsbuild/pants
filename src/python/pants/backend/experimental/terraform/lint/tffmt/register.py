# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.terraform.lint.tffmt.tffmt import rules as tffmt_rules


def rules():
    return [
        *tffmt_rules(),
    ]
