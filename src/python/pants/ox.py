# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

# True if this is being run as an oxidized binary.
is_oxidized = False


# Patch for PyOxidizer
if not sys.argv[0]:
    sys.argv[0] = "PLACEHOLDER_BINARY"
    is_oxidized = True
