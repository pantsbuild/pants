#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import os
import platform
import subprocess
import tempfile
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Iterator, List, Optional

from common import banner, die, green, travis_section


def main() -> None:
    banner("CI BEGINS")

    args = create_parser().parse_args()
    setup_environment(python_version=args.python_version)

    with maybe_get_remote_execution_oauth_token_path(
        remote_execution_enabled=args.remote_execution_enabled
    ) as remote_execution_oauth_token_path:

        if args.bootstrap:
            bootstrap(
                clean=args.bootstrap_clean,
                try_to_skip_rust_compilation=args.bootstrap_try_to_skip_rust_compilation,
                python_version=args.python_version,
            )
        set_run_from_pex()

        if args.githooks:
            run_githooks()
        if args.smoke_tests:
            run_smoke_tests()
        if args.lint:
            run_lint(oauth_token_path=remote_execution_oauth_token_path)
        if args.clippy:
            run_clippy()
        if args.cargo_audit:
            run_cargo_audit()
        if args.unit_tests:
            run_unit_tests(oauth_token_path=remote_execution_oauth_token_path)
        if args.rust_tests:
            run_rust_tests()
        if args.integration_tests:
            run_integration_tests(oauth_token_path=remote_execution_oauth_token_path)
        if args.platform_specific_tests:
            run_platform_specific_tests()

    banner("CI ENDS")
    print()
    green("SUCCESS")


# -------------------------------------------------------------------------
# Options
# -------------------------------------------------------------------------


class PythonVersion(Enum):
    py36 = "3.6"
    py37 = "3.7"

    def __str__(self) -> str:
        return str(self.value)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Runs commons tests for local or hosted CI.")
    parser.add_argument(
        "--python-version",
        type=PythonVersion,
        choices=list(PythonVersion),
        default=PythonVersion.py36,
        help="Run Pants with this version (defaults to 3.6).",
    )
    parser.add_argument(
        "--remote-execution-enabled",
        action="store_true",
        help="Pants will use remote build execution remote where possible (for now, the V2 unit tests). "
        "If running locally, you must be logged in via the `gcloud` CLI to an account with remote "
        "build execution permissions. If running in CI, the script will ping the secure token "
        "generator at https://github.com/pantsbuild/rbe-token-server.",
    )
    parser.add_argument(
        "--bootstrap", action="store_true", help="Bootstrap a pants.pex from local sources."
    )
    parser.add_argument(
        "--bootstrap-clean",
        action="store_true",
        help="Before bootstrapping, clean the environment so that it's like a fresh git clone.",
    )
    parser.add_argument(
        "--bootstrap-try-to-skip-rust-compilation",
        action="store_true",
        help=(
            "If possible, i.e. `native_engine.so` if is already present, don't rebuild the Rust "
            "engine. Otherwise, build. This means that you may end up using an outdated version of "
            "native_engine.so; this option should generally be avoided."
        ),
    )
    parser.add_argument("--githooks", action="store_true", help="Run pre-commit githook.")
    parser.add_argument(
        "--smoke-tests",
        action="store_true",
        help="Run smoke tests of bootstrapped Pants and repo BUILD files.",
    )
    parser.add_argument("--lint", action="store_true", help="Run lint over whole codebase.")
    parser.add_argument("--clippy", action="store_true", help="Run Clippy on Rust code.")
    parser.add_argument(
        "--cargo-audit", action="store_true", help="Run Cargo audit of Rust dependencies."
    )
    parser.add_argument("--unit-tests", action="store_true", help="Run Python unit tests.")
    parser.add_argument("--rust-tests", action="store_true", help="Run Rust tests.")
    parser.add_argument(
        "--integration-tests", action="store_true", help="Run Python integration tests."
    )
    parser.add_argument(
        "--platform-specific-tests", action="store_true", help="Test platform-specific behavior."
    )
    return parser


# -------------------------------------------------------------------------
# Set up the environment
# -------------------------------------------------------------------------


def setup_environment(*, python_version: PythonVersion):
    set_cxx_compiler()
    set_pants_dev()
    setup_python_interpreter(python_version)


def set_pants_dev() -> None:
    """We do this because we are running against a Pants clone."""
    os.environ["PANTS_DEV"] = "1"


def set_cxx_compiler() -> None:
    compiler = "g++" if platform.system() != "Darwin" else "clang++"
    os.environ["CXX"] = compiler


def setup_python_interpreter(version: PythonVersion) -> None:
    if "PY" not in os.environ:
        os.environ["PY"] = f"python{version}"
    constraints_env_var = "PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS"
    if constraints_env_var not in os.environ:
        os.environ[constraints_env_var] = f"['CPython=={version}.*']"
    banner(f"Setting interpreter constraints to {os.environ[constraints_env_var]}")


def set_run_from_pex() -> None:
    # Even though our Python integration tests and commands in this file directly invoke `pants.pex`,
    # some places like the JVM tests may still directly call the script `./pants`. When this happens,
    # we want to ensure that the script immediately breaks out to `./pants.pex` to avoid
    # re-bootstrapping Pants in CI.
    os.environ["RUN_PANTS_FROM_PEX"] = "1"


@contextmanager
def maybe_get_remote_execution_oauth_token_path(
    *, remote_execution_enabled: bool
) -> Iterator[Optional[str]]:
    if not remote_execution_enabled:
        yield None
        return
    command = (
        ["./pants.pex", "run", "build-support/bin:get_rbe_token"]
        if os.getenv("CI")
        else ["gcloud", "auth", "application-default", "print-access-token"]
    )
    token: str = subprocess.run(
        command, encoding="utf-8", stdout=subprocess.PIPE, check=True
    ).stdout
    if not os.getenv("CI"):
        token = token.splitlines()[0]
    with tempfile.NamedTemporaryFile(mode="w+") as tf:
        tf.write(token)
        tf.seek(0)
        yield tf.name


# -------------------------------------------------------------------------
# Bootstrap pants.pex
# -------------------------------------------------------------------------


def bootstrap(
    *, clean: bool, try_to_skip_rust_compilation: bool, python_version: PythonVersion
) -> None:
    with travis_section("Bootstrap", f"Bootstrapping Pants as a Python {python_version} PEX"):
        if clean:
            try:
                subprocess.run(["./build-support/python/clean.sh"], check=True)
            except subprocess.CalledProcessError:
                die("Failed to clean before bootstrapping Pants.")

        try:
            skip_native_engine_so_bootstrap = (
                try_to_skip_rust_compilation
                and Path("src/python/pants/engine/internals/native_engine.so").exists()
            )
            subprocess.run(
                ["./build-support/bin/bootstrap_pants_pex.sh"],
                check=True,
                env={
                    **os.environ,
                    "SKIP_NATIVE_ENGINE_SO_BOOTSTRAP": (
                        "true" if skip_native_engine_so_bootstrap else "false"
                    ),
                },
            )
        except subprocess.CalledProcessError:
            die("Failed to bootstrap Pants.")


def check_pants_pex_exists() -> None:
    if not Path("pants.pex").is_file():
        die(
            "pants.pex not found! Either run `./build-support/bin/ci.py --bootstrap` or check that "
            "AWS is properly downloading the uploaded `pants.pex`."
        )


# -------------------------------------------------------------------------
# Test commands
# -------------------------------------------------------------------------


def _use_remote_execution(oauth_token_path: str) -> List[str]:
    return [
        "--pants-config-files=pants.remote.toml",
        f"--remote-oauth-bearer-token-path={oauth_token_path}",
    ]


def _run_command(
    command: List[str],
    *,
    slug: str,
    start_message: str,
    die_message: str,
    requires_pex: bool = True,
) -> None:
    with travis_section(slug, start_message):
        if requires_pex:
            check_pants_pex_exists()
        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError:
            die(die_message)


def _test_command(
    *, oauth_token_path: Optional[str] = None, extra_args: Optional[List[str]] = None
) -> List[str]:
    targets = ["build-support::", "src::", "tests::", "pants-plugins::"]
    command = ["./pants.pex", "test", *targets]
    if extra_args:
        command.extend(extra_args)
    if oauth_token_path:
        command.extend(_use_remote_execution(oauth_token_path))
    return command


def run_githooks() -> None:
    _run_command(
        ["./build-support/githooks/pre-commit"],
        slug="PreCommit",
        start_message="Running pre-commit checks.",
        die_message="Pre-commit checks failed.",
    )


def run_smoke_tests() -> None:
    def run_check(command: List[str]) -> None:
        print(f"* Executing `./pants.pex {' '.join(command)}` as a smoke test")
        try:
            subprocess.run(
                ["./pants.pex", *command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                check=True,
            )
        except subprocess.CalledProcessError:
            die(f"Failed to execute `./pants {command}`.")

    checks = [
        ["goals"],
        ["list", "::"],
        ["roots"],
        ["target-types"],
    ]
    with travis_section("SmokeTest", "Smoke testing bootstrapped Pants and repo BUILD files"):
        check_pants_pex_exists()
        for check in checks:
            run_check(check)


def run_lint(*, oauth_token_path: Optional[str] = None) -> None:
    targets = ["build-support::", "examples::", "src::", "tests::"]
    command = ["./pants.pex", "--tag=-nolint", "lint", "typecheck", *targets]
    if oauth_token_path:
        command.extend(_use_remote_execution(oauth_token_path))
    _run_command(
        command,
        slug="Lint",
        start_message="Running lint checks.",
        die_message="Lint check failure.",
    )


def run_clippy() -> None:
    _run_command(
        ["build-support/bin/check_clippy.sh"],
        slug="RustClippy",
        start_message="Running Clippy on Rust code.",
        die_message="Clippy failure.",
        requires_pex=False,
    )


def run_cargo_audit() -> None:
    with travis_section("CargoAudit", "Running Cargo audit on Rust code"):
        try:
            subprocess.run(
                [
                    "build-support/bin/native/cargo",
                    "ensure-installed",
                    "--package=cargo-audit",
                    "--version=0.11.2",
                ],
                check=True,
            )
            subprocess.run(
                [
                    "build-support/bin/native/cargo",
                    "audit",
                    "-f",
                    "src/rust/engine/Cargo.lock",
                    # TODO(John Sirois): Kill --ignore RUSTSEC-2019-0003 when we can upgrade to an official
                    # released version of protobuf with a fix.
                    # See: https://github.com/pantsbuild/pants/issues/7760 for context.
                    "--ignore",
                    "RUSTSEC-2019-0003",
                ],
                check=True,
            )
        except subprocess.CalledProcessError:
            die("Cargo audit failure")


def run_rust_tests() -> None:
    is_macos = platform.system() == "Darwin"
    command = [
        "build-support/bin/native/cargo",
        "test",
        "--all",
        # We pass --tests to skip doc tests, because our generated protos contain invalid doc tests in
        # their comments.
        "--tests",
        "--manifest-path=src/rust/engine/Cargo.toml",
        "--",
        "--nocapture",
    ]
    if is_macos:
        # The osx travis environment has a low file descriptors ulimit, so we avoid running too many
        # tests in parallel.
        command.append("--test-threads=1")
    with travis_section("RustTests", "Running Rust tests"):
        try:
            subprocess.run(command, env={**os.environ, "RUST_BACKTRACE": "all"}, check=True)
        except subprocess.CalledProcessError:
            die("Rust test failure.")


def run_unit_tests(*, oauth_token_path: Optional[str] = None) -> None:
    _run_command(
        command=_test_command(oauth_token_path=oauth_token_path, extra_args=["--tag=-integration"]),
        slug="UnitTestsV2Local",
        start_message="Running unit tests.",
        die_message="Unit test failure.",
    )


def run_integration_tests(*, oauth_token_path: Optional[str] = None) -> None:
    _run_command(
        command=_test_command(oauth_token_path=oauth_token_path, extra_args=["--tag=+integration"]),
        slug="IntegrationTests",
        start_message="Running integration tests.",
        die_message="Integration test failure.",
    )


def run_platform_specific_tests() -> None:
    _run_command(
        command=_test_command(extra_args=["--tag=+platform_specific_behavior"]),
        slug="PlatformSpecificTests",
        start_message=f"Running platform-specific tests on platform {platform.system()}",
        die_message="Platform-specific test failure.",
    )


if __name__ == "__main__":
    main()
