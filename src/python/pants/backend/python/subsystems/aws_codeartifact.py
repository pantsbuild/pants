# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import BoolOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import help_text, softwrap


class PythonAwsCodeartifact(Subsystem):
    options_scope = "python-aws-codeartifact"

    help = help_text(
        """
        AWS CodeArtifact configuration

        These options are used to configure Pants to obtain and renew an AWS CodeArtifact token to access
        a PyPi-compatible CodeArtifact repository.
        """
    )

    enabled = BoolOption(
        default=False,
        help=softwrap(
            """
            If True, Pants will renew the AWS CodeArtifact token if it has expired. The token will be made
            availbale to Pex/Pip automatically.
            """
        ),
    )

    domain = StrOption(
        default="", help="AWS CodeArtifact domain containing the relevant repositories"
    )

    domain_owner = StrOption(
        default=None,
        help=softwrap(
            """
            If set, the value will be used as the `domainOwner` parameter passed to AWS CodeArtifact's GetAuthorizationToken API.
            """
        ),
    )
