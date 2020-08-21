# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# isort:skip_file

from pants.base.deprecated import deprecated_module
from pants.testutil.pants_integration_test import (  # noqa: F401
    PantsIntegrationTest as PantsRunIntegrationTest,
)
from pants.testutil.pants_integration_test import PantsResult as PantsResult  # noqa: F401

deprecated_module(
    removal_version="2.1.0.dev0", hint_message="Use pants.testutil.pants_integration_test"
)
