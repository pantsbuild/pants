# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Any, Dict, Tuple, Type

from pants.build_graph.aliased_target import AliasTarget
from pants.build_graph.target import Target


class DependencyContext:

    alias_types = (AliasTarget, Target)
    types_with_closure: Tuple[Type, ...] = ()
    target_closure_kwargs: Dict[str, Any] = {}
