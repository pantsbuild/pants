# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

# Provide the `is_oxidized` symbol, to allow for workarounds in Pants code where we use things
# that don't work under PyOxidizer's custom importer. `oxidized_importer` is only accessible
# in Pants under PyOxidizer, so an import failure will occur if we're not oxidized.
try:
    import oxidized_importer  # type: ignore # pants: no-infer-dep # noqa: F401

    is_oxidized = True
except ModuleNotFoundError:
    is_oxidized = False


if is_oxidized and not sys.argv[0]:
    # A not insignificant amount of Pants code relies on `sys.argv[0]`, which is modified in an
    # invalid way by python's `pymain_run_module` support. For our purposes, the executable
    # distribution is the correct `argv[0]`.
    # See https://github.com/indygreg/PyOxidizer/issues/307
    sys.argv[0] = sys.executable
