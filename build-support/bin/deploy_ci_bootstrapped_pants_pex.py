#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

from common import banner

# NB: We expect the `aws` CLI to already be installed.

TRAVIS_BUILD_DIR = os.environ["TRAVIS_BUILD_DIR"]
AWS_BUCKET = os.environ["AWS_BUCKET"]

PEX_KEY_PREFIX = os.environ["BOOTSTRAPPED_PEX_KEY_PREFIX"]
PEX_KEY_SUFFIX = os.environ["BOOTSTRAPPED_PEX_KEY_SUFFIX"]
PEX_KEY = f"{PEX_KEY_PREFIX}.{PEX_KEY_SUFFIX}"
PEX_URL = f"s3://{AWS_BUCKET}/{PEX_KEY}"

AWS_COMMAND_PREFIX = ["aws", "--no-sign-request", "--region", "us-east-1"]


def main() -> None:
    banner(f"Deploying `pants.pex` to {PEX_URL}.")
    deploy_pants_pex()


def deploy_pants_pex() -> None:
    subprocess.run(
        [*AWS_COMMAND_PREFIX, "s3", "cp", f"{TRAVIS_BUILD_DIR}/pants.pex", PEX_URL], check=True
    )


if __name__ == "__main__":
    main()
