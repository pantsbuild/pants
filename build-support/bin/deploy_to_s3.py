#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess


def main() -> None:
  install_aws_cli()
  configure_auth()
  deploy()


def install_aws_cli() -> None:
  subprocess.run(["./build-support/bin/install_aws_cli_for_ci.sh"], check=True)


def configure_auth() -> None:
  def set_value(key: str, value: str) -> None:
    subprocess.run(["aws", "configure", "set", key, value], check=True)

  set_value("aws_access_key_id", "AKIAIWOKBXVU3JLY6EGQ")
  set_value(
    "aws_secret_access_key",
    "UBVbpdYJ81OsDGKlPRBw6FlPJGlxosnFQ4A1xBbU5GwEBfv90GoKc6J0UwF+I4CDwytj/BlAks1XbW0zYX0oeIlXDnl1Vf"
    "ikm1k4hfIr6VCLHKppiU69FlEs+ph0Dktz8+aUWhrvJzICZs6Gu08kTBQ5++3ulDWDeTHqjr713YM="
  )


def deploy() -> None:
  # NB: we use the sync command to avoid transferring files that have not changed. See
  # https://github.com/pantsbuild/pants/issues/7258.
  subprocess.run(
    ["aws", "s3", "sync", "--acl", "public-read", "dist/deploy", "s3://binaries/pantsbuild.org"],
    check=True
  )


if __name__ == '__main__':
  main()
