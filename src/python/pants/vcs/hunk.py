# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.collection import Collection
from pants.engine.internals.native_engine import Hunk as Hunk  # noqa: F401
from pants.engine.internals.native_engine import TextBlock as TextBlock  # noqa: F401


class TextBlocks(Collection[TextBlock]):
    pass
