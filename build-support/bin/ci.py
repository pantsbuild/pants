#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import os
import platform
import subprocess
from enum import Enum, auto
from pathlib import Path
from typing import Iterable, List, NamedTuple, Optional, Set, Union

from common import banner, die, green, travis_section


def main() -> None:
    banner("CI BEGINS")

    args = create_parser().parse_args()
    setup_environment(python_version=args.python_version)

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
        run_lint()
    if args.doc_gen:
        run_doc_gen_tests()
    if args.clippy:
        run_clippy()
    if args.cargo_audit:
        run_cargo_audit()
    if args.unit_tests:
        run_unit_tests()
    if args.rust_tests:
        run_rust_tests()
    if args.jvm_tests:
        run_jvm_tests()
    if args.integration_tests_v1:
        run_integration_tests_v1(shard=args.integration_shard)
    if args.integration_tests_v2:
        run_integration_tests_v2(shard=args.integration_shard)
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
        help="Run Pants with this version (defaults to 3.6).",
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
    parser.add_argument("--doc-gen", action="store_true", help="Run doc generation tests.")
    parser.add_argument("--clippy", action="store_true", help="Run Clippy on Rust code.")
    parser.add_argument(
        "--cargo-audit", action="store_true", help="Run Cargo audit of Rust dependencies."
    )
    parser.add_argument("--unit-tests", action="store_true", help="Run Python unit tests.")
    parser.add_argument("--rust-tests", action="store_true", help="Run Rust tests.")
    parser.add_argument("--jvm-tests", action="store_true", help="Run JVM tests.")
    parser.add_argument(
        "--integration-tests-v1",
        action="store_true",
        help="Run Python integration tests w/ V1 runner.",
    )
    parser.add_argument(
        "--integration-tests-v2",
        action="store_true",
        help="Run Python integration tests w/ V2 runner.",
    )
    parser.add_argument(
        "--integration-shard",
        metavar="SHARD_NUMBER/TOTAL_SHARDS",
        default=None,
        help="Divide integration tests into TOTAL_SHARDS shards and just run those in SHARD_NUMBER. "
        "E.g. `-i 0/2` and `-i 1/2` will split the tests in half.",
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
    # Even though our Python integration tests and commands in this file directly invoke `pants.pex`,
    # some places like the JVM tests may still directly call the script `./pants`. When this happens,
    # we want to ensure that the script immediately breaks out to `./pants.pex` to avoid
    # re-bootstrapping Pants in CI.
    os.environ["RUN_PANTS_FROM_PEX"] = "1"


# -------------------------------------------------------------------------
# Block lists
# -------------------------------------------------------------------------

Target = str
Glob = str
TargetSet = Set[Target]


class TestStrategy(Enum):
    v1_no_chroot = auto()
    v1_chroot = auto()
    v2_local = auto()

    def pants_command(
        self, *, targets: Iterable[Union[Target, Glob]], shard: Optional[str] = None,
    ) -> List[str]:
        result = {
            self.v1_no_chroot: [
                "./pants.pex",
                "test.pytest",
                "--no-chroot",
                *sorted(targets),
                *PYTEST_PASSTHRU_ARGS,
            ],
            self.v1_chroot: ["./pants.pex", "test.pytest", *sorted(targets), *PYTEST_PASSTHRU_ARGS],
            self.v2_local: ["./pants.pex", "--no-v1", "--v2", "test", *sorted(targets)],
        }[
            self  # type: ignore[index]  # issues with understanding `self`
        ]
        if shard is not None and self in [self.v1_no_chroot, self.v1_chroot]:  # type: ignore[comparison-overlap]  # issues with understanding `self`
            result.insert(2, f"--test-pytest-test-shard={shard}")
        return result


class TestType(Enum):
    unit = "unit"
    integration = "integration"

    def __str__(self) -> str:
        return str(self.value)


class TestTargetSets(NamedTuple):
    v1_no_chroot: TargetSet
    v1_chroot: TargetSet
    v2_local: TargetSet

    @staticmethod
    def calculate(*, test_type: TestType) -> "TestTargetSets":
        def get_listed_targets(filename: str) -> TargetSet:
            list_path = Path(f"build-support/ci_lists/{filename}")
            if not list_path.exists():
                return set()
            return {line.strip() for line in list_path.read_text().splitlines()}

        all_targets = set(
            subprocess.run(
                [
                    "./pants.pex",
                    f"--tag={'-' if test_type == TestType.unit else '+'}integration",
                    "filter",
                    "--type=python_tests",
                    "build-support::",
                    "src/python::",
                    "tests/python::",
                    "contrib::",
                ],
                stdout=subprocess.PIPE,
                encoding="utf-8",
                check=True,
            )
            .stdout.strip()
            .split("\n")
        )

        v1_no_chroot_targets = get_listed_targets(f"{test_type}_chroot_block_list.txt")
        v1_chroot_targets = get_listed_targets(f"{test_type}_v2_block_list.txt")
        v2_local_targets = all_targets - v1_chroot_targets - v1_no_chroot_targets

        return TestTargetSets(
            v1_no_chroot=v1_no_chroot_targets,
            v1_chroot=v1_chroot_targets,
            v2_local=v2_local_targets,
        )


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

# We only want to output failures and skips.
# See https://docs.pytest.org/en/latest/usage.html#detailed-summary-report.
PYTEST_PASSTHRU_ARGS = ["--", "-q", "-rfa"]


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


def run_githooks() -> None:
    _run_command(
        ["./build-support/githooks/pre-commit"],
        slug="PreCommit",
        start_message="Running pre-commit checks",
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
        ["bash-completion"],
        ["reference"],
        ["clean-all"],
        ["goals"],
        ["list", "::"],
        ["roots"],
        ["targets"],
    ]
    with travis_section("SmokeTest", "Smoke testing Pants and repo BUILD files"):
        check_pants_pex_exists()
        for check in checks:
            run_check(check)


def run_lint() -> None:
    targets = ["contrib::", "examples::", "src::", "tests::", "zinc::"]
    command_prefix = ["./pants.pex", "--tag=-nolint"]
    _run_command(
        [*command_prefix, "--no-v1", "--v2", "lint", *targets],
        slug="Lint (V2)",
        start_message="Running V2 lint checks",
        die_message="Lint check failure.",
    )
    _run_command(
        [*command_prefix, "lint", *targets],
        slug="Lint (V1)",
        start_message="Running V1 lint checks",
        die_message="Lint check failure.",
    )


def run_doc_gen_tests() -> None:
    _run_command(
        ["build-support/bin/publish_docs.sh"],
        slug="DocGen",
        start_message="Running site doc generation test",
        die_message="Failed to generate site docs.",
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


def run_unit_tests() -> None:
    target_sets = TestTargetSets.calculate(test_type=TestType.unit)
    if target_sets.v2_local:
        _run_command(
            command=TestStrategy.v2_local.pants_command(targets=target_sets.v2_local),
            slug="UnitTestsV2Local",
            start_message="Running unit tests via local V2 strategy",
            die_message="Unit test failure (local V2)",
        )
    if target_sets.v1_chroot:
        _run_command(
            command=TestStrategy.v1_chroot.pants_command(targets=target_sets.v1_chroot),
            slug="UnitTestsV1Chroot",
            start_message="Running unit tests via local V1 chroot strategy",
            die_message="Unit test failure (V1 chroot)",
        )

    if target_sets.v1_no_chroot:
        _run_command(
            command=TestStrategy.v1_no_chroot.pants_command(targets=target_sets.v1_no_chroot),
            slug="UnitTestsV1NoChroot",
            start_message="Running unit tests via local V1 no-chroot strategy",
            die_message="Unit test failure (V1 no-chroot)",
        )


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


def run_jvm_tests() -> None:
    # NB: Ensure that this stays in sync with githooks/prepare-commit-msg.
    targets = ["src/java::", "src/scala::", "tests/java::", "tests/scala::", "zinc::"]
    _run_command(
        ["./pants.pex", "doc", "test", *targets],
        slug="CoreJVM",
        start_message="Running JVM tests",
        die_message="JVM test failure.",
    )


def run_integration_tests_v1(*, shard: Optional[str]) -> None:
    target_sets = TestTargetSets.calculate(test_type=TestType.integration)
    if target_sets.v1_no_chroot:
        _run_command(
            command=TestStrategy.v1_no_chroot.pants_command(
                targets=target_sets.v1_no_chroot, shard=shard
            ),
            slug="IntegrationTestsV1NoChroot",
            start_message="Running integration tests via V1 no-chroot strategy.",
            die_message="Integration test failure (V1 no-chroot)",
        )
    if target_sets.v1_chroot:
        _run_command(
            command=TestStrategy.v1_chroot.pants_command(
                targets=target_sets.v1_chroot, shard=shard
            ),
            slug="IntegrationTestsV1Chroot",
            start_message="Running integration tests via V1 chroot strategy.",
            die_message="Integration test failure (V1 chroot)",
        )


def run_integration_tests_v2(*, shard: Optional[str]) -> None:
    target_sets = TestTargetSets.calculate(test_type=TestType.integration)
    local_targets = sorted(target_sets.v2_local)

    if shard is None:
        selected_targets = local_targets
    else:
        shard_str, _, nshards_str = shard.partition("/")
        target_shard = int(shard_str)
        nshards = int(nshards_str)

        # See https://stackoverflow.com/a/14861842.
        q, r = divmod(len(local_targets), nshards)
        indices = [q * i + min(i, r) for i in range(nshards + 1)]
        partitions = [local_targets[indices[i] : indices[i + 1]] for i in range(nshards)]
        selected_targets = partitions[target_shard]

    _run_command(
        command=TestStrategy.v2_local.pants_command(targets=selected_targets),
        slug="IntegrationTestsV2Local",
        start_message="Running integration tests via V2 local strategy.",
        die_message="Integration test failure (V2 local)",
    )


def run_plugin_tests() -> None:
    _run_command(
        TestStrategy.v2_local.pants_command(targets={"pants-plugins/src/python::"}),
        slug="BackendTests",
        start_message="Running internal backend Python tests",
        die_message="Internal backend Python test failure.",
    )


def run_platform_specific_tests() -> None:
    command = TestStrategy.v1_no_chroot.pants_command(targets=["src/python/::", "tests/python::"])
    command.insert(1, "--tag=+platform_specific_behavior")
    _run_command(
        command,
        slug="PlatformSpecificTests",
        start_message=f"Running platform-specific tests on platform {platform.system()}",
        die_message="Pants platform-specific test failure.",
    )


if __name__ == "__main__":
    main()
