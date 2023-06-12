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

from pants_release.common import die

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
    parser.add_argument(
        "--acl",
        help="An optional ACL to set on copied objects.",
    )
    options = parser.parse_args()
    perform_copy(
        src_prefix=options.src_prefix,
        dst_prefix=options.dst_prefix,
        path=options.path,
        region=options.region,
        acl=options.acl,
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
    region: str,
    acl: str | None = None,
    aws_cli_symlink_path: str | None = None,
) -> None:
    """Recursively copy the files at src_prefix/src_path to S3.

    :param src_prefix: A relpath under the cwd.
    :param dst_prefix: An S3 URL prefix, of the form s3://bucket/path_prefix.
    :param path: The relpath under the src_prefix to copy.
      src_prefix/path will be (recursively) copied to dst_prefix/path.
      If empty, the entire src_prefix will be copied.
    :param region: The AWS region to access (should be the one the bucket is in).
    :param acl: An optional ACL to set on the copied objects.
    :param aws_cli_symlink_path: If specified, symlink the aws cli into this dir. Otherwise,
      it will be synlinked into the system standard Path.
    """
    if shutil.which("aws") is None:
        _install_aws_cli(symlink_path=aws_cli_symlink_path)
    _validate_authentication()
    _copy(src_prefix=src_prefix, dst_prefix=dst_prefix, path=path, region=region, acl=acl)


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


def _copy(src_prefix: str, dst_prefix: str, path: str, region: str, acl: str | None = None) -> None:
    _validate_relpath(src_prefix, "src_prefix")
    _validate_relpath(path, "path")
    if not dst_prefix.startswith("s3://"):
        raise ValueError("Destination URL must be of the form s3://<bucket>/<path>")
    if dst_prefix.endswith("/"):
        raise ValueError("Destination URL must not end with a slash")

    copy_from = os.path.join(src_prefix, path)
    copy_to = f"{dst_prefix}/{path}"

    if not os.path.exists(copy_from):
        logger.warning(f"Local path {copy_from} does not exist. Skipping copy to s3.")
        return

    # NB: we use the sync command to avoid transferring files that have not changed. See
    # https://github.com/pantsbuild/pants/issues/7258.
    cmd = [
        "aws",
        "--region",
        region,
        "s3",
        "sync",
        # This instructs the sync command to ignore timestamps, which we must do to allow
        # distinct shards—which may finish building their wheels at different times—to not
        # overwrite otherwise-identical wheels.
        "--size-only",
        # Turn off the dynamic progress display, which clutters the CI output.
        "--no-progress",
        *(["--acl", acl] if acl else []),
        copy_from,
        copy_to,
    ]
    _run(cmd)


if __name__ == "__main__":
    main()
