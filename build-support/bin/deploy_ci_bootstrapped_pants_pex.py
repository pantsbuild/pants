#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import os
import subprocess

from common import banner

# NB: We expect the `aws` CLI to already be installed and for authentication to be
# configured.

TRAVIS_BUILD_DIR = os.environ["TRAVIS_BUILD_DIR"]
PEX_URL_PREFIX = os.environ["BOOTSTRAPPED_PEX_URL_PREFIX"]
PEX_KEY_SUFFIX = os.environ["BOOTSTRAPPED_PEX_KEY_SUFFIX"]
PEX_URL = f"{PEX_URL_PREFIX}.{PEX_KEY_SUFFIX}"

NATIVE_ENGINE_SO_PATH = f"{TRAVIS_BUILD_DIR}/src/python/pants/engine/native_engine.so"
NATIVE_ENGINE_SO_URL_PREFIX = "s3://native_engine_so"
AWS_S3_COMMAND_PREFIX = ["aws", "--no-sign-request", "--region", "us-east-1", "s3"]


def main() -> None:
    args = create_parser().parse_args()

    native_engine_so_hash = calculate_native_engine_so_hash()
    native_engine_so_aws_directory = f"{NATIVE_ENGINE_SO_URL_PREFIX}/{native_engine_so_hash}"
    native_engine_so_aws_url = f"{native_engine_so_aws_directory}/native_engine.so"
    native_engine_so_already_cached = native_engine_so_in_s3_cache(native_engine_so_aws_directory)

    if args.get:
        if native_engine_so_already_cached:
            banner(
                f"`native_engine.so` found in the AWS S3 cache at {native_engine_so_aws_url}. "
                f"Downloading to avoid unnecessary Rust compilation."
            )
            get_native_engine_so(native_engine_so_aws_url)
        else:
            banner("`native_engine.so` not found in the AWS S3 cache. Recompiling Rust...")

    if args.deploy:
        if not native_engine_so_already_cached:
            banner(f"Deploying `native_engine.so` to {native_engine_so_aws_url}.")
            deploy_native_engine_so(native_engine_so_aws_url)
        banner(f"Deploying `pants.pex` to {PEX_URL}.")
        deploy_pants_pex()


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check that all .py files start with the appropriate header."
    )
    parser.add_argument(
        "--maybe-get-native-engine-so",
        dest="get",
        action="store_true",
        help="If `native_engine.so` is already in AWS S3, copy it down locally.",
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy both `pants.pex` and (if relevant) `native_engine.so`.",
    )
    return parser


def calculate_native_engine_so_hash() -> str:
    return (
        subprocess.run(
            ["build-support/bin/native/print_engine_hash.sh"], stdout=subprocess.PIPE, check=True,
        )
        .stdout.decode()
        .strip()
    )


def native_engine_so_in_s3_cache(native_engine_so_aws_directory: str) -> bool:
    # NB: This will fail if the bucket does not exist.
    ls_result = subprocess.run(
        [*AWS_S3_COMMAND_PREFIX, "ls", native_engine_so_aws_directory], stdout=subprocess.PIPE
    )
    return ls_result.returncode == 0 and "native_engine.so" in ls_result.stdout.decode()


def get_native_engine_so(native_engine_so_aws_url: str) -> None:
    subprocess.run(
        [*AWS_S3_COMMAND_PREFIX, "cp", native_engine_so_aws_url, NATIVE_ENGINE_SO_PATH], check=True
    )


def _deploy(file_path: str, s3_url: str) -> None:
    subprocess.run([*AWS_S3_COMMAND_PREFIX, "cp", file_path, s3_url], check=True)


def deploy_native_engine_so(native_engine_so_aws_url: str) -> None:
    _deploy(file_path=NATIVE_ENGINE_SO_PATH, s3_url=native_engine_so_aws_url)


def deploy_pants_pex() -> None:
    _deploy(f"{TRAVIS_BUILD_DIR}/pants.pex", PEX_URL)


if __name__ == "__main__":
    main()
