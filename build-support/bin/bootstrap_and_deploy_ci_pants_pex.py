#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import json
import os
import subprocess

from common import banner, die

# NB: We expect the `aws` CLI to already be installed.

TRAVIS_BUILD_DIR = os.environ["TRAVIS_BUILD_DIR"]
AWS_BUCKET = os.environ["AWS_BUCKET"]

PEX_KEY_PREFIX = os.environ["BOOTSTRAPPED_PEX_KEY_PREFIX"]
PEX_KEY_SUFFIX = os.environ["BOOTSTRAPPED_PEX_KEY_SUFFIX"]
PEX_KEY = f"{PEX_KEY_PREFIX}.{PEX_KEY_SUFFIX}"
PEX_URL = f"s3://{AWS_BUCKET}/{PEX_KEY}"

NATIVE_ENGINE_SO_KEY_PREFIX = os.environ["NATIVE_ENGINE_SO_KEY_PREFIX"]
NATIVE_ENGINE_SO_LOCAL_PATH = f"{TRAVIS_BUILD_DIR}/src/python/pants/engine/native_engine.so"

AWS_COMMAND_PREFIX = ["aws", "--no-sign-request", "--region", "us-east-1"]


def main() -> None:
    # NB: we must set `$PY` before calling `bootstrap()` to ensure that we use the exact same
    # Python interpreter when calculating the hash of `native_engine.so` as the one we use when
    # calling `ci.py --bootstrap`.
    python_version = create_parser().parse_args().python_version
    if "PY" not in os.environ:
        os.environ["PY"] = f"python{python_version}"

    native_engine_so_hash = calculate_native_engine_so_hash()
    native_engine_so_aws_key = (
        f"{NATIVE_ENGINE_SO_KEY_PREFIX}/{native_engine_so_hash}/native_engine.so"
    )
    native_engine_so_aws_url = f"s3://{AWS_BUCKET}/{native_engine_so_aws_key}"
    native_engine_so_already_cached = native_engine_so_in_s3_cache(native_engine_so_aws_key)

    if native_engine_so_already_cached:
        banner(
            f"`native_engine.so` found in the AWS S3 cache at {native_engine_so_aws_url}. "
            f"Downloading to avoid unnecessary Rust compilation."
        )
        get_native_engine_so(native_engine_so_aws_url)
    else:
        banner(
            f"`native_engine.so` not found in the AWS S3 cache at {native_engine_so_aws_url}. "
            f"Recompiling Rust..."
        )

    bootstrap_pants_pex(python_version)

    if native_engine_so_already_cached:
        banner(f"`native_engine.so` already cached at {native_engine_so_aws_url}. Skipping deploy.")
    else:
        banner(f"Deploying `native_engine.so` to {native_engine_so_aws_url}.")
        deploy_native_engine_so(native_engine_so_aws_url)

    banner(f"Deploying `pants.pex` to {PEX_URL}.")
    deploy_pants_pex()


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--python-version", type=float, help="The Python version to bootstrap pants.pex with.",
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


def native_engine_so_in_s3_cache(native_engine_so_aws_key: str) -> bool:
    ls_output = subprocess.run(
        [
            *AWS_COMMAND_PREFIX,
            "s3api",
            "list-object-versions",
            "--bucket",
            AWS_BUCKET,
            "--prefix",
            native_engine_so_aws_key,
            "--max-items",
            "2",
        ],
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.decode()
    if not ls_output:
        return False
    num_versions = len(json.loads(ls_output)["Versions"])
    if num_versions > 1:
        die(
            f"Multiple copies found of {native_engine_so_aws_key} in AWS S3. This is not allowed "
            "as a security precaution. Please raise this failure in the #infra channel "
            "in Slack so that we may investigate how this happened and delete the duplicate "
            "copy from S3."
        )
    return True


def bootstrap_pants_pex(python_version: float) -> None:
    subprocess.run(
        [
            "./build-support/bin/ci.py",
            "--bootstrap",
            "--bootstrap-try-to-skip-rust-compilation " f"--python-version",
            str(python_version),
        ],
        check=True,
    )


def get_native_engine_so(native_engine_so_aws_url: str) -> None:
    subprocess.run(
        [*AWS_COMMAND_PREFIX, "s3", "cp", native_engine_so_aws_url, NATIVE_ENGINE_SO_LOCAL_PATH],
        check=True,
    )


def _deploy(file_path: str, s3_url: str) -> None:
    subprocess.run([*AWS_COMMAND_PREFIX, "s3", "cp", file_path, s3_url], check=True)


def deploy_native_engine_so(native_engine_so_aws_url: str) -> None:
    _deploy(file_path=NATIVE_ENGINE_SO_LOCAL_PATH, s3_url=native_engine_so_aws_url)


def deploy_pants_pex() -> None:
    _deploy(f"{TRAVIS_BUILD_DIR}/pants.pex", PEX_URL)


if __name__ == "__main__":
    main()
