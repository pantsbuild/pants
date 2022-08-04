# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

# True if this is being run as an oxidized binary.
is_oxidized = False


# Patch for PyOxidizer
if not sys.argv[0]:
    # A giant pile of pants consumer code copies around `sys.argv`, which is modified in an
    # invalid way by python's `pymain_run_module` support. For our purposes, the executable
    # distribution is the correct `argv[0]`.
    # See https://github.com/indygreg/PyOxidizer/issues/307
    sys.argv[0] = sys.executable
    is_oxidized = True
