# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.rust.goals import tailor
from pants.backend.rust.target_types import RustCrateTarget


def target_types():
    return (RustCrateTarget,)


def rules():
    return (*tailor.rules(),)

