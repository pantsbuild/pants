# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.codegen.thrift import dependency_inference, tailor, target_types


def rules():
    return (
        *dependency_inference.rules(),
        *tailor.rules(),
        *target_types.rules(),
    )
