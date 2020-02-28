# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import deprecated_module
from pants.python.python_setup import PythonSetup as PythonSetup

deprecated_module("1.27.0.dev0", "Import from pants.python.python_setup instead.")


PythonSetup = PythonSetup
