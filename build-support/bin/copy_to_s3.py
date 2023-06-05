#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
from pathlib import PurePath

from common import die

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--src-prefix", required=True, help="A subdirectory of the cwd to copy files from."
    )
    parser.add_argument("--dst-prefix", required=True, help="An s3 URL to copy to.")
    parser.add_argument(
        "--path",
        default="",
        help=(
            "A subdirectory of --src-prefix to copy to the same relative path under --dst-prefix. "
            "That is, src_prefix/path will be copied to dst_prefix/path. If unspecified, the "
            "entire src_prefix will be copied."
        ),
    )
    parser.add_argument(
        "--region",
        help="The AWS region to connect to.",
        default="us-east-1",
    )
    options = parser.parse_args()
    perform_copy(
        src_prefix=options.src_prefix,
        dst_prefix=options.dst_prefix,
        path=options.path,
        dst_region=options.dst_region,
    )


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
        logger.error(f"stdout:\n{ex.stdout.decode()}\n")
        logger.error(f"stderr:\n{ex.stderr.decode()}\n")
        raise


def perform_copy(
    *,
    src_prefix: str,
    dst_prefix: str,
    path: str,
    dst_region: str,
    aws_cli_symlink_path: str | None = None,
) -> None:
    """Recursively copy the files at src_prefix/src_path to S3.

    :param src_prefix: A relpath under the cwd.
    :param dst_prefix: An S3 URL prefix, of the form s3://bucket/path_prefix.
    :param path: The relpath under the src_prefix to copy.
      src_prefix/path will be (recursively) copied to dst_prefix/path.
      If empty, the entire src_prefix will be copied.
    :param dst_region:  The AWS region to access (should be the one the bucket is in).
    :param aws_cli_symlink_path: If specified, symlink the aws cli into this dir. Otherwise,
      it will be synlinked into the system standard Path.
    """
    if shutil.which("aws") is None:
        _install_aws_cli(symlink_path=aws_cli_symlink_path)
    _validate_authentication()
    _copy(src_prefix=src_prefix, dst_prefix=dst_prefix, path=path, dst_region=dst_region)


def _install_aws_cli(symlink_path: str | None = None) -> None:
    env = {"AWS_CLI_SYMLINK_PATH": symlink_path} if symlink_path else {}
    _run(["./build-support/bin/install_aws_cli.sh"], env={**os.environ, **env})


def _validate_authentication() -> None:
    access_key_id = "AWS_ACCESS_KEY_ID"
    if access_key_id not in os.environ:
        die(f"Must set {access_key_id}.")
    secret_access_key = "AWS_SECRET_ACCESS_KEY"
    if secret_access_key not in os.environ:
        die(f"Must set {secret_access_key}.")


def _validate_relpath(path_str: str, descr: str) -> None:
    path = PurePath(path_str)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"{descr} `{path_str}` must be a relative path with no parent refs")


def _copy(src_prefix: str, dst_prefix: str, path: str, dst_region: str) -> None:
    _validate_relpath(src_prefix, "src_prefix")
    _validate_relpath(path, "path")
    if not dst_prefix.startswith("s3://"):
        raise ValueError("Destination URL must be of the form s3://<bucket>/<path>")
    if dst_prefix.endswith("/"):
        raise ValueError("Destination URL must not end with a slash")

    copy_from = os.path.join(src_prefix, path)
    copy_to = f"{dst_prefix}/{path}"

    # NB: we use the sync command to avoid transferring files that have not changed. See
    # https://github.com/pantsbuild/pants/issues/7258.
    _run(
        [
            "aws",
            "--region",
            dst_region,
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
            copy_from,
            copy_to,
        ]
    )


if __name__ == "__main__":
    main()
