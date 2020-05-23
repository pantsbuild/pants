#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import json
import os
import subprocess
from pathlib import Path

from common import banner, die

# NB: We expect the `aws` CLI to already be installed.

AWS_COMMAND_PREFIX = ["aws", "--no-sign-request", "--region", "us-east-1"]


def main() -> None:
    if not Path("src/python/pants").is_dir():
        raise ValueError(
            "This script assumes that you are in the Pants build root. Instead, you are at "
            f"{Path.cwd()}."
        )
    args = create_parser().parse_args()
    pex_url = f"s3://{args.aws_bucket}/{args.pex_key}"
    native_engine_so_local_path = "./src/python/pants/engine/internals/native_engine.so"

    # NB: we must set `$PY` before calling `bootstrap()` to ensure that we use the exact same
    # Python interpreter when calculating the hash of `native_engine.so` as the one we use when
    # calling `ci.py --bootstrap`.
    python_version = create_parser().parse_args().python_version
    if "PY" not in os.environ:
        os.environ["PY"] = f"python{python_version}"

    native_engine_so_hash = calculate_native_engine_so_hash()
    native_engine_so_aws_key = (
        f"{args.native_engine_so_key_prefix}/{native_engine_so_hash}/native_engine.so"
    )
    native_engine_so_aws_url = f"s3://{args.aws_bucket}/{native_engine_so_aws_key}"

    if native_engine_so_in_s3_cache(
        aws_bucket=args.aws_bucket, native_engine_so_aws_key=native_engine_so_aws_key
    ):
        banner(
            f"`native_engine.so` found in the AWS S3 cache at {native_engine_so_aws_url}. "
            f"Downloading to avoid unnecessary Rust compilation."
        )
        get_native_engine_so(
            native_engine_so_aws_url=native_engine_so_aws_url,
            native_engine_so_local_path=native_engine_so_local_path,
        )
    else:
        banner(
            f"`native_engine.so` not found in the AWS S3 cache at {native_engine_so_aws_url}. "
            f"Recompiling Rust..."
        )

    bootstrap_pants_pex(python_version)

    if native_engine_so_in_s3_cache(
        aws_bucket=args.aws_bucket, native_engine_so_aws_key=native_engine_so_aws_key
    ):
        banner(f"`native_engine.so` already cached at {native_engine_so_aws_url}. Skipping deploy.")
    else:
        banner(f"Deploying `native_engine.so` to {native_engine_so_aws_url}.")
        deploy_native_engine_so(
            native_engine_so_aws_url=native_engine_so_aws_url,
            native_engine_so_local_path=native_engine_so_local_path,
        )

    banner(f"Deploying `pants.pex` to {pex_url}.")
    deploy_pants_pex(pex_url=pex_url)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aws-bucket", required=True, help="Name of the S3 bucket.")
    parser.add_argument(
        "--pex-key", required=True, help="Key to use with S3 for the bootstrapped pants.pex"
    )
    parser.add_argument(
        "--native-engine-so-key-prefix",
        required=True,
        help=(
            "The key prefix for `native_engine.so`, which will get combined with the unique hash "
            "to determine the key."
        ),
    )
    parser.add_argument(
        "--python-version",
        type=float,
        required=True,
        help="The Python version to bootstrap pants.pex with.",
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


def native_engine_so_in_s3_cache(*, aws_bucket: str, native_engine_so_aws_key: str) -> bool:
    ls_output = subprocess.run(
        [
            *AWS_COMMAND_PREFIX,
            "s3api",
            "list-object-versions",
            "--bucket",
            aws_bucket,
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
    versions = json.loads(ls_output).get("Versions")
    if versions is None:
        return False
    if len(versions) > 1:
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
            "--bootstrap-try-to-skip-rust-compilation",
            "--python-version",
            str(python_version),
        ],
        check=True,
    )


def get_native_engine_so(
    *, native_engine_so_aws_url: str, native_engine_so_local_path: str
) -> None:
    subprocess.run(
        [*AWS_COMMAND_PREFIX, "s3", "cp", native_engine_so_aws_url, native_engine_so_local_path],
        check=True,
    )


def _deploy(file_path: str, s3_url: str) -> None:
    subprocess.run([*AWS_COMMAND_PREFIX, "s3", "cp", file_path, s3_url], check=True)


def deploy_native_engine_so(
    *, native_engine_so_aws_url: str, native_engine_so_local_path: str
) -> None:
    _deploy(file_path=native_engine_so_local_path, s3_url=native_engine_so_aws_url)


def deploy_pants_pex(pex_url: str) -> None:
    _deploy("./pants.pex", pex_url)


if __name__ == "__main__":
    main()
