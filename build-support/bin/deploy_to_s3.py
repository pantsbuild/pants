#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
import subprocess
from typing import Tuple

from common import die


def main() -> None:
  if shutil.which("aws") is None:
    install_aws_cli()
  access_key_id, secret_access_key = get_auth_values()
  set_auth(access_key_id=access_key_id, secret_access_key=secret_access_key)
  deploy()


def install_aws_cli() -> None:
  subprocess.run(["./build-support/bin/install_aws_cli_for_ci.sh"], check=True)


def get_auth_values() -> Tuple[str, str]:
  def get_value(key: str) -> str:
    val = os.environ.get(key, None)
    if val is not None:
      return val
    die(f"Caller of the script must set the env var {key}.")

  return get_value("AWS_DEPLOY_ACCESS_KEY_ID"), get_value("AWS_DEPLOY_SECRET_ACCESS_KEY")


def set_auth(*, access_key_id: str, secret_access_key: str) -> None:
  def set_value(key: str, value: str) -> None:
    subprocess.run(["aws", "configure", "set", key, value], check=True)

  set_value("aws_access_key_id", access_key_id)
  set_value("aws_secret_access_key", secret_access_key)


def deploy() -> None:
  # NB: we use the sync command to avoid transferring files that have not changed. See
  # https://github.com/pantsbuild/pants/issues/7258.
  subprocess.run(
    ["aws", "s3", "sync", "--acl", "public-read", "dist/deploy", "s3://binaries/pantsbuild.org"],
    check=True
  )


if __name__ == '__main__':
  main()
