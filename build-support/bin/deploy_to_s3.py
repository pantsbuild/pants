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
  check_authentication_setup()
  deploy()


def install_aws_cli() -> None:
  subprocess.run(["./build-support/bin/install_aws_cli_for_ci.sh"], check=True)


def check_authentication_setup() -> None:
  access_key_id = "AWS_ACCESS_KEY_ID"
  secret_access_key = "AWS_SECRET_ACCESS_KEY"
  if access_key_id not in os.environ or secret_access_key not in os.environ:
    die(f"Caller of the script must set both {access_key_id} and {secret_access_key}.")


def deploy() -> None:
  # NB: we use the sync command to avoid transferring files that have not changed. See
  # https://github.com/pantsbuild/pants/issues/7258.
  subprocess.run(
    ["aws", "s3", "sync", "--acl", "public-read", "dist/deploy", "s3://binaries.pantsbuild.org"],
    check=True
  )


if __name__ == '__main__':
  main()
