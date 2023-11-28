# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.bsp.goal import BSPGoal
from pants.bsp.rules import rules as bsp_rules


def builtin_goals():
    return (BSPGoal,)


def rules():
    return (*bsp_rules(),)
