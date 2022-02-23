# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import ClassVar

from pants.engine.unions import union


@union
class BSPLanguageSupport:
    """Union exposed by language backends to inform BSP core rules of capabilities to advertise to
    clients."""

    language_id: ClassVar[str]
    can_compile: bool = False
    can_test: bool = False
    can_run: bool = False
    can_debug: bool = False
