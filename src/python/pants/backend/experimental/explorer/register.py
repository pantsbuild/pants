# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.explorer.goal import rules as explorer_rules


def rules():
    return (*explorer_rules(),)
