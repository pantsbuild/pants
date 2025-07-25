# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from enum import Enum

from pants.option.option_types import EnumOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class S3AuthSigning(Enum):
    SIGV4 = "sigv4"
    HMACV1 = "hmacv1"


class S3Subsystem(Subsystem):
    options_scope = "s3-url-handler"
    help = "AWS S3 URL handler options"

    auth_signing = EnumOption(
        default=S3AuthSigning.SIGV4,
        help=softwrap(
            """
            The authentication signing behavior to use when making requests to S3.

            Available options:
            - sigv4: Use AWS Signature Version 4 signing process (default and recommended)
            - hmacv1: Use the legacy HmacV1 signing process
            """
        ),
    )
