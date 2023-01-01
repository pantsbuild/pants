#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess

from common import die

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


def _run(args, env=None) -> None:
    try:
        subprocess.run(
            args=args,
            env=env,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as ex:
        logger.error(f"Process `{' '.join(args)}` failed with exit code {ex.returncode}.")
        logger.error(f"stdout: {ex.stdout}")
        logger.error(f"stderr: {ex.stderr}")
        raise


def perform_deploy(*, aws_cli_symlink_path: str | None = None, scope: str | None = None) -> None:
    """Deploy the contents of dist/deploy to S3.

    The `aws` CLI app will be installed if needed and will be symlinked into the system standard
    $PATH unless `aws_cli_symlink_path` is provided, in which case it will be symlinked into that
    directory.

    The full contents of the local dist/deploy directory will be synced to The S3 bucket mounted at
    https://binaries.pantsbuild.org unless a scope is provided, in which case just that subdirectory
    of dist/deploy will be synced to the corresponding "path" under https://binaries.pantsbuild.org.
    """
    if shutil.which("aws") is None:
        install_aws_cli(symlink_path=aws_cli_symlink_path)
    validate_authentication()
    deploy(scope=scope)


def install_aws_cli(symlink_path: str | None = None) -> None:
    env = {"AWS_CLI_SYMLINK_PATH": symlink_path} if symlink_path else {}
    _run(["./build-support/bin/install_aws_cli.sh"], env={**os.environ, **env})


def validate_authentication() -> None:
    access_key_id = "AWS_ACCESS_KEY_ID"
    if access_key_id not in os.environ:
        die(f"Must set {access_key_id}.")
    secret_access_key = "AWS_SECRET_ACCESS_KEY"
    if secret_access_key not in os.environ:
        die(f"Must set {secret_access_key}.")


def deploy(scope: str | None = None) -> None:
    # NB: we use the sync command to avoid transferring files that have not changed. See
    # https://github.com/pantsbuild/pants/issues/7258.

    local_path = "dist/deploy"
    s3_dest = "s3://binaries.pantsbuild.org"
    if scope:
        local_path = f"{local_path}/{scope}"
        s3_dest = f"{s3_dest}/{scope}"

    _run(
        [
            "aws",
            "s3",
            "sync",
            # This instructs the sync command to ignore timestamps, which we must do to allow
            # distinct shards—which may finish building their wheels at different times—to not
            # overwrite otherwise-identical wheels.
            "--size-only",
            # Turn off the dynamic progress display, which clutters the CI output.
            "--no-progress",
            "--acl",
            "public-read",
            str(local_path),
            s3_dest,
        ]
    )

    # Create/update the index file in S3.  After running on both the MacOS and Linux shards
    # the index file will contain the wheels for both.
    wheels_dir = "dist/deploy/wheels/pantsbuild.pants"
    if os.path.isdir(wheels_dir):
        for sha in os.listdir(wheels_dir):
            _run(["./build-support/bin/create_s3_index_file.sh", sha])


if __name__ == "__main__":
    main()
