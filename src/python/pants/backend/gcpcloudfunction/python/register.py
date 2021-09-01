# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Create GCP Cloud Functions from Python code.

FIXME See https://www.pantsbuild.org/docs/awslambda-python.
"""

from pants.backend.gcpcloudfunction.python import lambdex
from pants.backend.gcpcloudfunction.python import rules as python_rules
from pants.backend.gcpcloudfunction.python.target_types import PythonGCPCloudFunction
from pants.backend.gcpcloudfunction.python.target_types import rules as target_types_rules


def rules():
    return (*python_rules.rules(), *target_types_rules(), *lambdex.rules())


def target_types():
    return [PythonGCPCloudFunction]
