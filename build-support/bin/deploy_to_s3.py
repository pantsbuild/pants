#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import logging

from copy_to_s3 import perform_copy

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scope",
        help=(
            "The subdirectory of dist/deploy to deploy to S3; by default, everything under that "
            "directory."
        ),
    )
    options = parser.parse_args()
    perform_deploy(scope=options.scope)


def perform_deploy(*, aws_cli_symlink_path: str | None = None, scope: str | None = None) -> None:
    """Deploy the contents of dist/deploy to S3.

    The `aws` CLI app will be installed if needed and will be symlinked into the system standard
    $PATH unless `aws_cli_symlink_path` is provided, in which case it will be symlinked into that
    directory.

    The full contents of the local dist/deploy directory will be synced to The S3 bucket mounted at
    https://binaries.pantsbuild.org unless a scope is provided, in which case just that subdirectory
    of dist/deploy will be synced to the corresponding "path" under https://binaries.pantsbuild.org.
    """
    perform_copy(
        src_prefix="dist/deploy",
        dst_prefix="s3://binaries.pantsbuild.org",
        path=scope or "",
        region="us-east-1",
        acl="public-read",
        aws_cli_symlink_path=aws_cli_symlink_path,
    )


if __name__ == "__main__":
    main()
