# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence

from pants.engine.rules import side_effecting
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)

name_value_re = re.compile(r"([A-Za-z_]\w*)=(.*)")
shorthand_re = re.compile(r"([A-Za-z_]\w*)")


@side_effecting
@frozen_after_init
@dataclass(unsafe_hash=True)
class PantsEnvironment:
    """PantsEnvironment is a representation of the environment variables the currently-executing
    pants process was invoked with.

    Since the exact contents of the environment are very specific to a given invocation of pants,
    this type is marked as side-effecting, and can only be requested as an input to an uncacheable
    rule. An uncacheable rule should accept this type as an input, and use `get_subset` to filter
    the environment rules down to only the ones other rules care about as inputs, in order to avoid
    a lot of cache invalidation if the environment changes spuriously.
    """

    env: FrozenDict[str, str]

    def __init__(self, env: Optional[Mapping[str, str]] = None):
        """Initialize a `PantsEnvironment` with the current contents of the environment.

        Explicitly specify the env argument to create a mock environment for testing.
        """

        self.env = FrozenDict(env if env else os.environ)

    def get_subset(self, requested: Sequence[str]) -> FrozenDict[str, Optional[str]]:
        """Given a list of extra environment variable specifiers as strings, filter the contents of
        the pants environment to only the variables that were specified as a pants configuration
        option."""

        env_var_subset: Dict[str, Optional[str]] = {}

        for env_var in requested:
            name_value_match = name_value_re.match(env_var)
            if name_value_match:
                env_var_subset[name_value_match[1]] = name_value_match[2]
            elif shorthand_re.match(env_var):
                env_var_subset[env_var] = self.env.get(env_var)
            else:
                raise ValueError(
                    f"An invalid variable was requested via the --test-extra-env-var mechanism: {env_var}"
                )

        return FrozenDict(env_var_subset)
