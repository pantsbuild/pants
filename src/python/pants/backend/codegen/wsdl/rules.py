# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.wsdl import tailor, target_types


def rules():
    return [*tailor.rules(), *target_types.rules()]
