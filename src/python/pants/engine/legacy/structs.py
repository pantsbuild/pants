# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.internals.struct import StructWithDeps


class TargetAdaptor(StructWithDeps):
    """A Struct to imitate the existing Target.

    Extends StructWithDeps to add a `dependencies` field marked Addressable.
    """
