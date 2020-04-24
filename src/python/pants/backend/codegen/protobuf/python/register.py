# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.python import gen_rules


def rules():
    return [
        *gen_rules.rules(),
    ]
