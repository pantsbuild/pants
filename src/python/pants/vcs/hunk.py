# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.engine.internals.target_adaptor import Block


@dataclass(frozen=True)
class Hunk:
    """Hunk of difference in unified format.

    https://www.gnu.org/software/diffutils/manual/html_node/Detailed-Unified.html
    """

    left: Block
    right: Block
