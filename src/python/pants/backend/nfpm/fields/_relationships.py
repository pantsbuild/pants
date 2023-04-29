# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta

from pants.engine.target import StringSequenceField

class NfpmPackageRelationshipsField(StringSequenceField, metaclass=ABCMeta):
    pass
