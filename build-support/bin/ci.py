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
from typing import Iterator, List, Optional, Set

from common import banner, die, green, travis_section


def main() -> None:
  banner("CI BEGINS")

  args = create_parser().parse_args()
  setup_environment(python_version=args.python_version)

  if args.bootstrap:
    bootstrap(clean=args.bootstrap_clean, python_version=args.python_version)
  set_run_from_pex()

  if args.githooks:
    run_githooks()
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
  if args.unit_tests:
    run_unit_tests(remote_execution_enabled=args.remote_execution_enabled)
  if args.rust_tests:
    run_rust_tests()
  if args.jvm_tests:
    run_jvm_tests()
  if args.integration_tests:
    run_integration_tests(shard=args.integration_shard)
  if args.plugin_tests:
    run_plugin_tests()
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
    help="Run Pants with this version (defaults to 3.6)."
  )
  parser.add_argument(
    "--remote-execution-enabled", action="store_true",
    help="Pants will use remote build execution remote where possible (for now, the V2 unit tests). "
         "If running locally, you must be logged in via the `gcloud` CLI to an account with remote "
         "build execution permissions. If running in CI, the script will ping the secure token "
         "generator at https://github.com/pantsbuild/rbe-token-server."
  )
  parser.add_argument(
    "--bootstrap", action="store_true", help="Bootstrap a pants.pex from local sources."
  )
  parser.add_argument(
    "--bootstrap-clean", action="store_true",
    help="Before bootstrapping, clean the environment so that it's like a fresh git clone."
  )
  parser.add_argument("--githooks", action="store_true", help="Run pre-commit githook.")
  parser.add_argument(
    "--sanity-checks", action="store_true",
    help="Run sanity checks of bootstrapped Pants and repo BUILD files."
  )
  parser.add_argument("--lint", action="store_true", help="Run lint over whole codebase.")
  parser.add_argument("--doc-gen", action="store_true", help="Run doc generation tests.")
  parser.add_argument("--clippy", action="store_true", help="Run Clippy on Rust code.")
  parser.add_argument(
    "--cargo-audit", action="store_true", help="Run Cargo audit of Rust dependencies."
  )
  parser.add_argument(
    "--unit-tests", action="store_true",
    help="Run Python unit tests."
  )
  parser.add_argument("--rust-tests", action="store_true", help="Run Rust tests.")
  parser.add_argument("--jvm-tests", action="store_true", help="Run JVM tests.")
  parser.add_argument(
    "--integration-tests", action="store_true", help="Run Python integration tests."
  )
  parser.add_argument(
    "--integration-shard", metavar="SHARD_NUMBER/TOTAL_SHARDS", default=None,
    help="Divide integration tests into TOTAL_SHARDS shards and just run those in SHARD_NUMBER. "
         "E.g. `-i 0/2` and `-i 1/2` will split the tests in half."
  )
  parser.add_argument("--plugin-tests", action="store_true", help="Run tests for pants-plugins.")
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
  # We want all invocations of ./pants (apart from the bootstrapping one above) to delegate
  # to ./pants.pex, and not themselves attempt to bootstrap.
  # In this file we invoke ./pants.pex directly anyway, but some of those invocations will run
  # integration tests that shell out to `./pants`, so we set this env var for those cases.
  os.environ["RUN_PANTS_FROM_PEX"] = "1"


@contextmanager
def get_remote_execution_oauth_token_path() -> Iterator[str]:
  command = (
    ["./pants.pex", "--quiet", "run", "build-support/bin:get_rbe_token"]
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
# Blacklists
# -------------------------------------------------------------------------

def get_blacklisted_targets(filename: str) -> Set[str]:
  return {
    line.strip()
    for line in Path(f"build-support/ci_blacklists/{filename}").read_text().splitlines()
  }


def get_all_python_tests(*, tag: Optional[str] = None) -> Set[str]:
  command = [
    "./pants.pex",
    "--filter-type=python_tests",
    "filter",
    "src/python::",
    "tests/python::",
    "contrib::"
  ]
  if tag is not None:
    command.insert(1, f"--tag={tag}")
  return set(subprocess.run(
    command, stdout=subprocess.PIPE, encoding="utf-8", check=True
  ).stdout.strip().split("\n"))

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


def check_pants_pex_exists() -> None:
  if not Path("pants.pex").is_file():
    die("pants.pex not found! Either run `./build-support/bin/ci.py --bootstrap` or check that "
        "AWS is properly downloading the uploaded `pants.pex`.")

# -------------------------------------------------------------------------
# Test commands
# -------------------------------------------------------------------------

# We only want to output failures and skips.
# See https://docs.pytest.org/en/latest/usage.html#detailed-summary-report.
PYTEST_PASSTHRU_ARGS = ["--", "-q", "-rfa"]


def _run_command(
  command: List[str], *, slug: str, start_message: str, die_message: str, requires_pex: bool = True
) -> None:
  with travis_section(slug, start_message):
    if requires_pex:
      check_pants_pex_exists()
    try:
      subprocess.run(command, check=True)
    except subprocess.CalledProcessError:
      die(die_message)


def run_githooks() -> None:
  _run_command(
    ["./build-support/githooks/pre-commit"],
    slug="PreCommit",
    start_message="Running pre-commit checks",
    die_message="Pre-commit checks failed."
  )


def run_sanity_checks() -> None:
  def run_check(command: List[str]) -> None:
    print(f"* Executing `./pants.pex {' '.join(command)}` as a sanity check")
    try:
      subprocess.run(
        ["./pants.pex"] + command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        check=True
      )
    except subprocess.CalledProcessError:
      die(f"Failed to execute `./pants {command}`.")

  checks = [
    ["bash-completion"],
    ["reference"],
    ["clean-all"],
    ["goals"],
    ["list", "::"],
    ["roots"],
    ["targets"]
  ]
  with travis_section("SanityCheck", "Sanity checking bootstrapped Pants and repo BUILD files"):
    check_pants_pex_exists()
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
    ["build-support/bin/publish_docs.sh"],
    slug="DocGen",
    start_message="Running site doc generation test",
    die_message="Failed to generate site docs."
  )


def run_clippy() -> None:
  _run_command(
    ["build-support/bin/check_clippy.sh"],
    slug="RustClippy",
    start_message="Running Clippy on Rust code",
    die_message="Clippy failure.",
    requires_pex=False,
  )


def run_cargo_audit() -> None:
  with travis_section("CargoAudit", "Running Cargo audit on Rust code"):
    try:
      subprocess.run([
        "build-support/bin/native/cargo",
        "ensure-installed",
        "--package=cargo-audit",
        "--version=0.7.0",
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


def run_unit_tests(*, remote_execution_enabled: bool) -> None:
  check_pants_pex_exists()

  all_targets = get_all_python_tests(tag="-integration")
  blacklisted_chroot_targets = get_blacklisted_targets("unit_test_chroot_blacklist.txt")
  blacklisted_v2_targets = get_blacklisted_targets("unit_test_v2_blacklist.txt")
  blacklisted_remote_targets = get_blacklisted_targets("unit_test_remote_blacklist.txt")

  v1_no_chroot_targets = blacklisted_chroot_targets
  v1_chroot_targets = blacklisted_v2_targets
  v2_local_targets = blacklisted_remote_targets
  v2_remote_targets = all_targets - v2_local_targets - v1_chroot_targets - v1_no_chroot_targets

  basic_command = ["./pants.pex", "test.pytest"]
  v2_command = ["./pants.pex", "--no-v1", "--v2", "test.pytest"]
  v1_no_chroot_command = basic_command + sorted(v1_no_chroot_targets) + PYTEST_PASSTHRU_ARGS
  v1_chroot_command = basic_command + ["--test-pytest-chroot"] + sorted(v1_chroot_targets) + PYTEST_PASSTHRU_ARGS
  v2_local_command = v2_command + sorted(v2_local_targets)

  if not remote_execution_enabled:
    v2_local_targets = v2_local_targets | v2_remote_targets
    v2_local_command = v2_command + sorted(v2_local_targets)
  else:
    with travis_section(
      "UnitTestsRemote", "Running unit tests via remote execution"
    ), get_remote_execution_oauth_token_path() as oauth_token_path:
      v2_remote_command = v2_command[:-1] + [
          "--pants-config-files=pants.remote.ini",
          # We turn off speculation to reduce the risk of flakiness, where a test passes locally but
          # fails remoting and we have a race condition for which environment executes first.
          "--process-execution-speculation-strategy=none",
          f"--remote-oauth-bearer-token-path={oauth_token_path}",
          "test.pytest",
        ] + sorted(v2_remote_targets)
      try:
        subprocess.run(v2_remote_command, check=True)
      except subprocess.CalledProcessError:
        die("Unit test failure (remote execution)")
      else:
        green("Unit tests passed (remote execution)")

  with travis_section("UnitTestsLocal", "Running unit tests via local execution"):
    try:
      subprocess.run(v2_local_command, check=True)
      subprocess.run(v1_chroot_command, check=True)
      subprocess.run(v1_no_chroot_command, check=True)
    except subprocess.CalledProcessError:
      die("Unit test failure (local execution)")
    else:
      green("Unit tests passed (local execution)")


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


def run_integration_tests(*, shard: Optional[str]) -> None:
  check_pants_pex_exists()
  all_targets = get_all_python_tests(tag="+integration")
  command = ["./pants.pex", "test.pytest"]
  if shard is not None:
    command.append(f"--test-pytest-test-shard={shard}")
  with travis_section("IntegrationTests", f"Running Pants Integration tests {shard if shard is not None else ''}"):
    try:
      subprocess.run(command + sorted(all_targets) + PYTEST_PASSTHRU_ARGS, check=True)
    except subprocess.CalledProcessError:
      die("Integration test failure.")


def run_plugin_tests() -> None:
  _run_command(
    ["./pants.pex",
     "test.pytest",
     "pants-plugins/src/python::",
     "pants-plugins/tests/python::",
     ] + PYTEST_PASSTHRU_ARGS,
    slug="BackendTests",
    start_message="Running internal backend Python tests",
    die_message="Internal backend Python test failure."
  )


def run_platform_specific_tests() -> None:
  targets = ["src/python/::", "tests/python::"]
  _run_command(
    ["./pants.pex",
     "--tag=+platform_specific_behavior",
     "test"
     ] + targets + PYTEST_PASSTHRU_ARGS,
    slug="PlatformSpecificTests",
    start_message=f"Running platform-specific tests on platform {platform.system()}",
    die_message="Pants platform-specific test failure."
  )


if __name__ == "__main__":
  main()
