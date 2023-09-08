# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Create Google Cloud Functions from Python code.

See https://www.pantsbuild.org/docs/google-cloud-function-python.
"""

from pants.backend.google_cloud_function.python import rules as python_rules
from pants.backend.google_cloud_function.python.target_types import PythonGoogleCloudFunction
from pants.backend.google_cloud_function.python.target_types import rules as target_types_rules


def rules():
    return (*python_rules.rules(), *target_types_rules())


def target_types():
    return [PythonGoogleCloudFunction]
