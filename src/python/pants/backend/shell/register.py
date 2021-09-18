# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.shell import dependency_inference, shunit2_test_runner, tailor
from pants.backend.shell.target_types import (
    ShellSourcesGeneratorTarget,
    Shunit2TestsGeneratorTarget,
)
from pants.backend.shell.target_types import rules as target_types_rules


def target_types():
    return [ShellSourcesGeneratorTarget, Shunit2TestsGeneratorTarget]


def rules():
    return [
        *dependency_inference.rules(),
        *tailor.rules(),
        *shunit2_test_runner.rules(),
        *target_types_rules(),
    ]
