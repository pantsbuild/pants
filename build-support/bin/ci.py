#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import os
import platform
import subprocess
from enum import Enum
from pathlib import Path
from typing import List, Optional

from common import banner, die, travis_section


def main() -> None:
  args = create_parser().parse_args()
  setup_environment(python_version=args.python_version)

  if args.bootstrap:
    bootstrap(clean=args.bootstrap_clean, python_version=args.python_version)
  set_run_from_pex()

  if args.precommit_checks:
    run_precommit_checks()
  if args.sanity_checks:
    run_sanity_checks()
  if args.lint:
    run_lint()
  if args.doc_gen:
    run_doc_gen_tests()
  if args.clippy:
    run_clippy()
  if args.cargo_audit:
    run_cargo_audit()
  if args.python:
    run_python_tests()
  if args.rust:
    run_rust_tests()
  if args.jvm:
    run_jvm_tests()
  if args.integration_tests:
    run_integration_tests(shard=args.integration_shard)
  if args.internal_backend_tests:
    run_internal_backend_tests()
  if args.platform_specific_tests:
    run_platform_specific_tests()

# -------------------------------------------------------------------------
# Options
# -------------------------------------------------------------------------

class PythonVersion(Enum):
  py27 = "2.7"
  py36 = "3.6"
  py37 = "3.7"

  def __str__(self) -> str:
    return str(self.value)


def create_parser() -> argparse.ArgumentParser:
  # TODO: reassign the short CLI flag names to reflect the long names.
  parser = argparse.ArgumentParser(description="Runs commons tests for local or hosted CI.")
  parser.add_argument(
    "-v", "--python-version",
    type=PythonVersion,
    choices=list(PythonVersion),
    default=PythonVersion.py36,
    help="Run Pants with this version (defaults to 3.6)."
  )
  parser.add_argument(
    "-b", "--bootstrap", action="store_true", help="Bootstrap a pants.pex from local sources."
  )
  parser.add_argument(
    "-x", "--bootstrap-clean", action="store_true",
    help="Before bootstrapping, clean the environment so that it's like a fresh git clone."
  )
  parser.add_argument(
    "-f", "--precommit-checks", action="store_true", help="Run pre-commit githook."
  )
  parser.add_argument(
    "-m", "--sanity-checks", action="store_true",
    help="Run sanity checks of bootstrapped Pants and repo BUILD files."
  )
  parser.add_argument(
    "-t", "--lint", action="store_true", help="Run lint over whole codebase."
  )
  parser.add_argument(
    "-r", "--doc-gen", action="store_true", help="Run doc generation tests."
  )
  parser.add_argument(
    "-s", "--clippy", action="store_true", help="Run Clippy on Rust code."
  )
  parser.add_argument(
    "-a", "--cargo-audit", action="store_true", help="Run Cargo audit of Rust dependencies."
  )
  parser.add_argument(
    "-p", "--python-tests", action="store_true", help="Run core Python unit tests."
  )
  parser.add_argument(
    "-e", "--rust-tests", action="store_true", help="Run Rust tests."
  )
  parser.add_argument(
    "-j", "--jvm-tests", action="store_true", help="Run JVM tests."
  )
  parser.add_argument(
    "-c", "--integration-tests", action="store_true", help="Run Python integration tests."
  )
  parser.add_argument(
    "-i", "--integration-shard", metavar="SHARD_NUMBER/TOTAL_SHARDS", default=None,
    help="Divide integration tests into TOTAL_SHARDS shards and just run those in SHARD_NUMBER. "
         "E.g. `-i 0/2` and `-i 1/2` will split the tests in half."
  )
  parser.add_argument(
    "-l", "--internal-backend-tests", action="store_true", help="Run internal backend Python tests."
  )
  parser.add_argument(
    "-z", "--platform-specific-tests", action="store_true", help="Test platform-specific behavior."
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
    os.environ["PY"] = str(version)
  constraints_env_var = "PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS"
  if constraints_env_var not in os.environ:
    os.environ[constraints_env_var] = f"['CPython=={version}.*']"
  banner(f"Setting interpreter constraints to {os.environ[constraints_env_var]}")


def set_run_from_pex() -> None:
  # We want all invocations of ./pants (apart from the bootstrapping one above) to delegate
  # to ./pants.pex, and not themselves attempt to bootstrap.
  # In this file we invoke ./pants.pex directly anyway, but some of those invocations will run
  # integration tests that shell out to `./pants`, so we set this env var for those cases.
  os.environ["RUN_PANTS_FROM_PEX"] = "1"

# -------------------------------------------------------------------------
# Bootstrap pants.pex
# -------------------------------------------------------------------------

def bootstrap(*, clean: bool, python_version: PythonVersion) -> None:
  with travis_section("Bootstrap", f"Bootstrapping Pants as a Python {python_version} PEX"):
    if clean:
      try:
        subprocess.run(["./build-support/python/clean.sh"], check=True)
      except subprocess.CalledProcessError:
        die("Failed to clean before bootstrapping Pants.")
    try:
      subprocess.run(["./pants", "binary", "src/python/pants/bin:pants_local_binary"], check=True)
      Path("dist/pants_local_binary.pex").rename("pants.pex")
      subprocess.run(["./pants.pex", "--version"], check=True)
    except subprocess.CalledProcessError:
      die("Failed to bootstrap Pants.")

# -------------------------------------------------------------------------
# Test commands
# -------------------------------------------------------------------------

# We only want to output failures and skips.
# See https://docs.pytest.org/en/latest/usage.html#detailed-summary-report.
PYTEST_PASSTHRU_ARGS = ["-q", "-rfa"]


def _run_command(command: List[str], *, slug: str, start_message: str, die_message: str) -> None:
  with travis_section(slug, start_message):
    try:
      subprocess.run(command, check=True)
    except subprocess.CalledProcessError:
      die(die_message)


def run_precommit_checks() -> None:
  _run_command(
    ["./build-support/githooks/pre-commit"],
    slug="PreCommit",
    start_message="Running pre-commit checks",
    die_message="Pre-commit checks failed."
  )


def run_sanity_checks() -> None:
  def run_check(command: str) -> None:
    print(f"* Executing `./pants.pex {command}` as a sanity check")
    try:
      subprocess.run(
        ["./pants.pex", command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        check=True
      )
    except subprocess.CalledProcessError:
      die(f"Failed to execute `./pants {command}`.")

  checks = ["bash-completion", "reference", "clean-all", "goals", "list ::", "roots", "targets"]
  with travis_section("SanityCheck", "Sanity checking bootstrapped Pants and repo BUILD files"):
    for check in checks:
      run_check(check)


def run_lint() -> None:
  targets = ["contrib::", "examples::", "src::", "tests::", "zinc::"]
  _run_command(
    ["./pants.pex", "--tag=-nolint", "lint"] + targets,
    slug="Lint",
    start_message="Running lint checks",
    die_message="Lint check failure."
  )


def run_doc_gen_tests() -> None:
  _run_command(
    ["build-support/bin/publish.docs.sh"],
    slug="DocGen",
    start_message="Running site doc generation test",
    die_message="Failed to generate site docs."
  )


def run_clippy() -> None:
  _run_command(
    ["build-support/bin/check_clippy.sh"],
    slug="RustClippy",
    start_message="Running Clippy on Rust code",
    die_message="Clippy failure."
  )


def run_cargo_audit() -> None:
  with travis_section("CargoAudit", "Running Cargo audit on Rust code"):
    try:
      subprocess.run([
        "build-support/bin/native/cargo",
        "ensure-installed",
        "--package=cargo-audit",
        "--version=0.6.1",
        # TODO(John Sirois): Kill --git-url/--git-rev when we upgrade to cargo-audit > 0.6.1.
        # See: https://github.com/pantsbuild/pants/issues/7760 for context.
        "--git-url=https://github.com/RustSec/cargo-audit",
        "--git-rev=1c298bcda2c74f4a1bd8f0d8482b3577ee94fbb3",
      ], check=True)
      subprocess.run([
        "build-support/bin/native/cargo",
        "audit",
        "-f", "src/rust/engine/Cargo.lock",
        # TODO(John Sirois): Kill --ignore RUSTSEC-2019-0003 when we can upgrade to an official
        # released version of protobuf with a fix.
        # See: https://github.com/pantsbuild/pants/issues/7760 for context.
        "--ignore", "RUSTSEC-2019-0003"
      ], check=True)
    except subprocess.CalledProcessError:
      die("Cargo audit failure")


# TODO
def run_python_tests() -> None:
  targets = ["src/java::", "src/scala::", "tests/java::", "tests/scala::", "zinc::"]
  _run_command(
    ["./pants.pex", "doc", "test"] + targets,
    slug="CoreJVM",
    start_message="Running core JVM tests",
    die_message="Core JVM test failure."
  )


def run_rust_tests() -> None:
  command = [
    "build-support/bin/native/cargo",
    "test",
    "--all",
    # We pass --tests to skip doc tests, because our generated protos contain invalid doc tests in
    # their comments.
    "--tests",
    "--manifest-path=src/rust/engine/Cargo.toml",
    "--",
    "--nocapture"
  ]
  if platform.system() == "Darwin":
    # The osx travis environment has a low file descriptors ulimit, so we avoid running too many
    # tests in parallel.
    command.append("--test-threads=1")
  with travis_section("RustTests", "Running Rust tests"):
    try:
      subprocess.run(command, env={**os.environ, "RUST_BACKTRACE": "all"}, check=True)
    except subprocess.CalledProcessError:
      die("Rust test failure.")


def run_jvm_tests() -> None:
  targets = ["src/java::", "src/scala::", "tests/java::", "tests/scala::", "zinc::"]
  _run_command(
    ["./pants.pex", "doc", "test"] + targets,
    slug="CoreJVM",
    start_message="Running JVM tests",
    die_message="JVM test failure."
  )


# TODO
def run_integration_tests(shard: Optional[str]) -> None:
  targets = ["src/java::", "src/scala::", "tests/java::", "tests/scala::", "zinc::"]
  _run_command(
    ["./pants.pex", "doc", "test"] + targets,
    slug="CoreJVM",
    start_message="Running core JVM tests",
    die_message="Core JVM test failure."
  )


def run_internal_backend_tests() -> None:
  _run_command(
    ["./pants.pex", "test.pytest", "pants-plugins/src/python::", "pants-plugins/tests/python::"] + PYTEST_PASSTHRU_ARGS,
    slug="BackendTests",
    start_message="Running internal backend Python tests",
    die_message="Internal backend Python test failure."
  )


def run_platform_specific_tests() -> None:
  targets = ["src/python/::", "tests/python::"]
  _run_command(
    ["./pants.pex", "--tag='+platform_specific_behavior'", "test"] + targets + PYTEST_PASSTHRU_ARGS,
    slug="PlatformSpecificTests",
    start_message=f"Running platform-specific tests on platform {platform.system()}",
    die_message="Pants platform-specific test failure."
  )


if __name__ == "__main__":
  main()
