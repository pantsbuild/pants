#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
import subprocess

from common import die


def main() -> None:
    if shutil.which("aws") is None:
        install_aws_cli()
    validate_authentication()
    deploy()


def install_aws_cli() -> None:
    subprocess.run(["./build-support/bin/install_aws_cli_for_ci.sh"], check=True)


def validate_authentication() -> None:
    access_key_id = "AWS_ACCESS_KEY_ID"
    if access_key_id not in os.environ:
        die(f"Must set {access_key_id}.")
    secret_access_key = "AWS_SECRET_ACCESS_KEY"
    if secret_access_key not in os.environ:
        die(f"Must set {secret_access_key}.")


def deploy() -> None:
    # NB: we use the sync command to avoid transferring files that have not changed. See
    # https://github.com/pantsbuild/pants/issues/7258.
    subprocess.run(
        [
            "aws",
            "s3",
            "sync",
            # This instructs the sync command to ignore timestamps, which we must do to allow
            # distinct shards—which may finish building their wheels at different times—to not
            # overwrite otherwise-identical wheels.
            "--size-only",
            "--acl",
            "public-read",
            "dist/deploy",
            "s3://binaries.pantsbuild.org",
        ],
        check=True,
    )

    # Create/update the index file in S3.  After running on both the MacOS and Linux shards
    # the index file will contain the wheels for both.
    for sha in os.listdir("dist/deploy/wheels/pantsbuild.pants/"):
        subprocess.run(["./build-support/bin/create_s3_index_file.sh", sha])


if __name__ == "__main__":
    main()
