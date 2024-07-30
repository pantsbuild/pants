# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# NB: This file needs to be separate from target_types.py to avoid import cycles.

from enum import Enum

from pants.engine.target import StringField
from pants.util.strutil import help_text


class AWSLambdaArchitecture(str, Enum):  # noqa: N818
    X86_64 = "x86_64"
    ARM64 = "arm64"


class AWSLambdaArchitectureField(StringField):
    alias = "architecture"
    valid_choices = AWSLambdaArchitecture
    expected_type = str
    default = AWSLambdaArchitecture.X86_64.value
    help = help_text(
        """
        The architecture of the AWS Lambda runtime to target (x86_64 or arm64).
        See https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html.
        """
    )
