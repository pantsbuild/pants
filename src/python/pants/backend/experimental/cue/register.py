# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.cue.rules import rules as cue_rules
from pants.backend.cue.target_types import CuePackageTarget


def target_types():
    return [
        CuePackageTarget,
    ]


def rules():
    return cue_rules()
