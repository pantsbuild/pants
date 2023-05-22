# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, Sequence, cast

import toml
import yaml
from common import die

from pants.util.strutil import softwrap

HEADER = dedent(
    """\
    # GENERATED, DO NOT EDIT!
    # To change, edit `build-support/bin/generate_github_workflows.py` and run:
    #   ./pants run build-support/bin/generate_github_workflows.py
    """
)


Step = Dict[str, Any]
Jobs = Dict[str, Any]
Env = Dict[str, str]


class Platform(Enum):
    LINUX_X86_64 = "Linux-x86_64"
    LINUX_ARM64 = "Linux-ARM64"
    MACOS10_15_X86_64 = "macOS10-15-x86_64"
    MACOS11_X86_64 = "macOS11-x86_64"
    MACOS11_ARM64 = "macOS11-ARM64"


GITHUB_HOSTED = {Platform.LINUX_X86_64, Platform.MACOS11_X86_64}
SELF_HOSTED = {Platform.LINUX_ARM64, Platform.MACOS10_15_X86_64, Platform.MACOS11_ARM64}
CARGO_AUDIT_IGNORED_ADVISORY_IDS = (
    "RUSTSEC-2020-0128",  # returns a false positive on the cache crate, which is a local crate not a 3rd party crate
)


def gha_expr(expr: str) -> str:
    """Properly quote GitHub Actions expressions.

    Because we use f-strings often, but not always, in this script, it is very easy to get the
    quoting of the double curly braces wrong, especially when changing a non-f-string to an f-string
    or vice versa. So instead we universally delegate to this function.
    """
    # Here we use simple string concat instead of getting tangled up with escaping in f-strings.
    return "${{ " + expr + " }}"


def hash_files(path: str) -> str:
    """Generate a properly quoted hashFiles call for the given path."""
    return gha_expr(f"hashFiles('{path}')")


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------


# NB: The `upload-artifact` action strips the longest common prefix of paths in the
# created artifact, but the `download-artifact` action needs to know what that prefix
# was.
NATIVE_FILES_COMMON_PREFIX = "src/python/pants"
NATIVE_FILES = [
    f"{NATIVE_FILES_COMMON_PREFIX}/bin/native_client",
    f"{NATIVE_FILES_COMMON_PREFIX}/engine/internals/native_engine.so",
    f"{NATIVE_FILES_COMMON_PREFIX}/engine/internals/native_engine.so.metadata",
]

# We don't specify a patch version so that we get the latest, which comes pre-installed:
#  https://github.com/actions/setup-python#available-versions-of-python
PYTHON_VERSION = "3.9"

DONT_SKIP_RUST = "needs.classify_changes.outputs.rust == 'true'"
DONT_SKIP_WHEELS = "needs.classify_changes.outputs.release == 'true'"
IS_PANTS_OWNER = "github.repository_owner == 'pantsbuild'"

# NB: This overrides `pants.ci.toml`.
DISABLE_REMOTE_CACHE_ENV = {"PANTS_REMOTE_CACHE_READ": "false", "PANTS_REMOTE_CACHE_WRITE": "false"}


# ----------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------


def classify_changes() -> Jobs:
    linux_x86_64_helper = Helper(Platform.LINUX_X86_64)
    return {
        "classify_changes": {
            "name": "Classify changes",
            "runs-on": linux_x86_64_helper.runs_on(),
            "if": IS_PANTS_OWNER,
            "outputs": {
                "docs_only": gha_expr("steps.classify.outputs.docs_only"),
                "docs": gha_expr("steps.classify.outputs.docs"),
                "rust": gha_expr("steps.classify.outputs.rust"),
                "release": gha_expr("steps.classify.outputs.release"),
                "ci_config": gha_expr("steps.classify.outputs.ci_config"),
                "other": gha_expr("steps.classify.outputs.other"),
            },
            "steps": [
                *checkout(),
                {
                    "id": "classify",
                    "name": "Classify changed files",
                    "run": dedent(
                        """\
                        if [[ -z $GITHUB_EVENT_PULL_REQUEST_BASE_SHA ]]; then
                          # push: compare to the immediate parent, which should already be fetched
                          # (checkout's fetch_depth defaults to 10)
                          comparison_sha=$(git rev-parse HEAD^)
                        else
                          # pull request: compare to the base branch, ensuring that commit exists
                          git fetch --depth=1 "$GITHUB_EVENT_PULL_REQUEST_BASE_SHA"
                          comparison_sha="$GITHUB_EVENT_PULL_REQUEST_BASE_SHA"
                        fi
                        echo "comparison_sha=$comparison_sha"

                        affected=$(git diff --name-only "$comparison_sha" HEAD | python build-support/bin/classify_changed_files.py)
                        echo "Affected:"
                        if [[ "${affected}" == "docs" ]]; then
                          echo "docs_only=true" | tee -a $GITHUB_OUTPUT
                        fi
                        for i in ${affected}; do
                          echo "${i}=true" | tee -a $GITHUB_OUTPUT
                        done
                        """
                    ),
                },
            ],
        },
    }


def ensure_category_label() -> Sequence[Step]:
    """Check that exactly one category label is present on a pull request."""
    return [
        {
            "if": "github.event_name == 'pull_request'",
            "name": "Ensure category label",
            "uses": "mheap/github-action-required-labels@v4.0.0",
            "env": {"GITHUB_TOKEN": gha_expr("secrets.GITHUB_TOKEN")},
            "with": {
                "mode": "exactly",
                "count": 1,
                "labels": softwrap(
                    """
                    category:new feature, category:user api change,
                    category:plugin api change, category:performance, category:bugfix,
                    category:documentation, category:internal
                    """
                ),
            },
        }
    ]


def checkout(
    *, fetch_depth: int = 10, containerized: bool = False, ref: str | None = None
) -> Sequence[Step]:
    """Get prior commits and the commit message."""
    fetch_depth_opt: dict[str, Any] = {"fetch-depth": fetch_depth}
    steps = [
        # See https://github.community/t/accessing-commit-message-in-pull-request-event/17158/8
        # for details on how we get the commit message here.
        # We need to fetch a few commits back, to be able to access HEAD^2 in the PR case.
        {
            "name": "Check out code",
            "uses": "actions/checkout@v3",
            "with": {
                **fetch_depth_opt,
                **({"ref": ref} if ref else {}),
            },
        },
    ]
    if containerized:
        steps.append(
            # Work around https://github.com/actions/checkout/issues/760 for our container jobs.
            # See:
            # + https://github.blog/2022-04-12-git-security-vulnerability-announced
            # + https://cve.mitre.org/cgi-bin/cvename.cgi?name=CVE-2022-24765
            {
                "name": "Configure Git",
                "run": 'git config --global safe.directory "$GITHUB_WORKSPACE"',
            }
        )
    return steps


def launch_bazel_remote() -> Sequence[Step]:
    return [
        {
            "name": "Launch bazel-remote",
            "if": "github.repository_owner == 'pantsbuild'",
            "run": dedent(
                """\
                mkdir -p ~/bazel-remote
                docker run -u 1001:1000 \
                  -v ~/bazel-remote:/data \
                  -p 9092:9092 \
                  buchgr/bazel-remote-cache \
                  --s3.auth_method=access_key \
                  --s3.secret_access_key="${AWS_SECRET_ACCESS_KEY}" \
                  --s3.access_key_id="${AWS_ACCESS_KEY_ID}" \
                  --s3.bucket=cache.pantsbuild.org \
                  --s3.endpoint=s3.us-east-1.amazonaws.com \
                  --max_size 30 \
                  &
                echo "PANTS_REMOTE_CACHE_READ=true" >> "$GITHUB_ENV"
                echo "PANTS_REMOTE_CACHE_WRITE=true" >> "$GITHUB_ENV"
                echo "PANTS_REMOTE_STORE_ADDRESS=grpc://localhost:9092" >> "$GITHUB_ENV"
                """
            ),
            "env": {
                "AWS_SECRET_ACCESS_KEY": f"{gha_expr('secrets.AWS_SECRET_ACCESS_KEY')}",
                "AWS_ACCESS_KEY_ID": f"{gha_expr('secrets.AWS_ACCESS_KEY_ID')}",
            },
        }
    ]


def global_env() -> Env:
    return {
        "PANTS_CONFIG_FILES": "+['pants.ci.toml']",
        "RUST_BACKTRACE": "all",
    }


def rust_channel() -> str:
    with open("rust-toolchain") as fp:
        rust_toolchain = toml.load(fp)
    return cast(str, rust_toolchain["toolchain"]["channel"])


def install_rustup() -> Step:
    return {
        "name": "Install rustup",
        "run": dedent(
            """\
            curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -v -y --default-toolchain none
            echo "${HOME}/.cargo/bin" >> $GITHUB_PATH
            """
        ),
    }


def install_jdk() -> Step:
    return {
        "name": "Install AdoptJDK",
        "uses": "actions/setup-java@v3",
        "with": {
            "distribution": "adopt",
            "java-version": "11",
        },
    }


def install_go() -> Step:
    return {
        "name": "Install Go",
        "uses": "actions/setup-go@v3",
        "with": {"go-version": "1.19.5"},
    }


def deploy_to_s3(
    name: str,
    *,
    scope: str | None = None,
) -> Step:
    run = "./build-support/bin/deploy_to_s3.py"
    if scope:
        run = f"{run} --scope {scope}"
    return {
        "name": name,
        "run": run,
        "env": {
            "AWS_SECRET_ACCESS_KEY": f"{gha_expr('secrets.AWS_SECRET_ACCESS_KEY')}",
            "AWS_ACCESS_KEY_ID": f"{gha_expr('secrets.AWS_ACCESS_KEY_ID')}",
        },
    }


def download_apache_thrift() -> Step:
    return {
        "name": "Download Apache `thrift` binary (Linux)",
        "if": "runner.os == 'Linux'",
        "run": dedent(
            """\
            mkdir -p "${HOME}/.thrift"
            curl --fail -L https://binaries.pantsbuild.org/bin/thrift/linux/x86_64/0.15.0/thrift -o "${HOME}/.thrift/thrift"
            chmod +x "${HOME}/.thrift/thrift"
            echo "${HOME}/.thrift" >> $GITHUB_PATH
            """
        ),
    }


class Helper:
    def __init__(self, platform: Platform):
        self.platform = platform

    def platform_name(self) -> str:
        return str(self.platform.value)

    def job_name_suffix(self) -> str:
        return self.platform_name().lower().replace("-", "_")

    def job_name(self, prefix: str) -> str:
        return f"{prefix}_{self.job_name_suffix()}"

    def runs_on(self) -> list[str]:
        # GHA strongly recommends targeting the self-hosted label as well as
        # any platform-specific labels, so we don't run on future GH-hosted
        # platforms without realizing it.
        ret = ["self-hosted"] if self.platform in SELF_HOSTED else []
        if self.platform == Platform.MACOS11_X86_64:
            ret += ["macos-11"]
        elif self.platform == Platform.MACOS11_ARM64:
            ret += ["macOS-11-ARM64"]
        elif self.platform == Platform.MACOS10_15_X86_64:
            ret += ["macOS-10.15-X64"]
        elif self.platform == Platform.LINUX_X86_64:
            ret += ["ubuntu-20.04"]
        elif self.platform == Platform.LINUX_ARM64:
            ret += ["Linux", "ARM64"]
        else:
            raise ValueError(f"Unsupported platform: {self.platform_name()}")
        return ret

    def platform_env(self):
        ret = {}
        if self.platform in {Platform.MACOS10_15_X86_64, Platform.MACOS11_X86_64}:
            # Works around bad `-arch arm64` flag embedded in Xcode 12.x Python interpreters on
            # intel machines. See: https://github.com/giampaolo/psutil/issues/1832
            ret["ARCHFLAGS"] = "-arch x86_64"
        if self.platform == Platform.MACOS11_ARM64:
            ret["ARCHFLAGS"] = "-arch arm64"
        if self.platform == Platform.LINUX_ARM64:
            ret["PANTS_CONFIG_FILES"] = "+['pants.ci.toml','pants.ci.aarch64.toml']"
        return ret

    def maybe_append_cargo_test_parallelism(self, cmd: str) -> str:
        if self.platform == Platform.LINUX_ARM64:
            # TODO: The ARM64 runner has enough cores to reliably trigger #18191 using
            # our default settings. We lower parallelism here as a bandaid to work around
            # #18191 until it can be resolved.
            return f"{cmd} --test-threads=8"
        return cmd

    def wrap_cmd(self, cmd: str) -> str:
        if self.platform == Platform.MACOS11_ARM64:
            # The self-hosted M1 runner is an X86_64 binary that runs under Rosetta,
            # so we have to explicitly change the arch for the subprocesses it spawns.
            return f"arch -arm64 {cmd}"
        return cmd

    def native_binaries_upload(self) -> Step:
        return {
            "name": "Upload native binaries",
            "uses": "actions/upload-artifact@v3",
            "with": {
                "name": f"native_binaries.{gha_expr('matrix.python-version')}.{self.platform_name()}",
                "path": "\n".join(NATIVE_FILES),
            },
        }

    def native_binaries_download(self) -> Sequence[Step]:
        return [
            {
                "name": "Download native binaries",
                "uses": "actions/download-artifact@v3",
                "with": {
                    "name": f"native_binaries.{gha_expr('matrix.python-version')}.{self.platform_name()}",
                    "path": NATIVE_FILES_COMMON_PREFIX,
                },
            },
            {
                "name": "Make native-client runnable",
                "run": f"chmod +x {NATIVE_FILES[0]}",
            },
        ]

    def rust_caches(self) -> Sequence[Step]:
        return [
            {
                "name": "Cache Rust toolchain",
                "uses": "actions/cache@v3",
                "with": {
                    "path": f"~/.rustup/toolchains/{rust_channel()}-*\n~/.rustup/update-hashes\n~/.rustup/settings.toml\n",
                    "key": f"{self.platform_name()}-rustup-{hash_files('rust-toolchain')}-v2",
                },
            },
            {
                "name": "Cache Cargo",
                "uses": "benjyw/rust-cache@461b9f8eee66b575bce78977bf649b8b7a8d53f1",
                "with": {
                    # If set, replaces the job id in the cache key, so that the cache is stable across jobs.
                    # If we don't set this, each job may restore from a previous job's cache entry (via a
                    # restore key) but will write its own entry, even if there were no rust changes.
                    # This will cause us to hit the 10GB limit much sooner, and also spend time uploading
                    # identical cache entries unnecessarily.
                    "shared-key": "engine",
                    "workspaces": "src/rust/engine",
                    # A custom option from our fork of the action.
                    "cache-bin": "false",
                },
            },
        ]

    def bootstrap_caches(self) -> Sequence[Step]:
        return [
            *self.rust_caches(),
            # NB: This caching is only intended for the bootstrap jobs to avoid them needing to
            # re-compile when possible. Compare to the upload-artifact and download-artifact actions,
            # which are how the bootstrap jobs share the compiled binaries with the other jobs like
            # `lint` and `test`.
            {
                "name": "Get native engine hash",
                "id": "get-engine-hash",
                "run": 'echo "hash=$(./build-support/bin/rust/print_engine_hash.sh)" >> $GITHUB_OUTPUT',
                "shell": "bash",
            },
            {
                "name": "Cache native engine",
                "uses": "actions/cache@v3",
                "with": {
                    "path": "\n".join(NATIVE_FILES),
                    "key": f"{self.platform_name()}-engine-{gha_expr('steps.get-engine-hash.outputs.hash')}-v1",
                },
            },
        ]

    def setup_primary_python(self) -> Sequence[Step]:
        ret = []
        # We pre-install Python on our self-hosted platforms.
        # We must set it up on Github-hosted platforms.
        if self.platform in GITHUB_HOSTED:
            ret.append(
                {
                    "name": f"Set up Python {PYTHON_VERSION}",
                    "uses": "actions/setup-python@v4",
                    "with": {"python-version": PYTHON_VERSION},
                }
            )
        return ret

    def expose_all_pythons(self) -> Sequence[Step]:
        ret = []
        # Self-hosted runners already have all relevant pythons exposed on their PATH, so we
        # only use this action on the GitHub-hosted platforms.
        if self.platform in GITHUB_HOSTED:
            ret.append(
                {
                    "name": "Expose Pythons",
                    "uses": "pantsbuild/actions/expose-pythons@627a8ce25d972afa03da1641be9261bbbe0e3ffe",
                }
            )
        return ret

    def bootstrap_pants(self) -> Sequence[Step]:
        return [
            *checkout(),
            *self.setup_primary_python(),
            *self.bootstrap_caches(),
            {
                "name": "Bootstrap Pants",
                # Check for a regression of https://github.com/pantsbuild/pants/issues/17470.
                "run": self.wrap_cmd(
                    f"./pants version > {gha_expr('runner.temp')}/_pants_version.stdout && "
                    f"[[ -s {gha_expr('runner.temp')}/_pants_version.stdout ]]"
                ),
            },
            {
                "name": "Run smoke tests",
                "run": dedent(
                    f"""\
                    {self.wrap_cmd("./pants list ::")}
                    {self.wrap_cmd("./pants roots")}
                    {self.wrap_cmd("./pants help goals")}
                    {self.wrap_cmd("./pants help targets")}
                    {self.wrap_cmd("./pants help subsystems")}
                    """
                ),
            },
            self.upload_log_artifacts(name="bootstrap"),
            self.native_binaries_upload(),
        ]

    def build_wheels(self) -> list[Step]:
        cmd = dedent(
            # Note that the build-local-pex run is just for smoke-testing that pex
            # builds work, and it must come *before* the build-wheels runs, since
            # it cleans out `dist/deploy`, which the build-wheels runs populate for
            # later attention by deploy_to_s3.py.
            """\
            ./pants run build-support/bin/release.py -- build-local-pex
            ./pants run build-support/bin/release.py -- build-wheels
            """
        )

        return [
            {
                "name": "Build wheels",
                "run": cmd,
                "env": self.platform_env(),
            },
        ]

    def upload_log_artifacts(self, name: str) -> Step:
        return {
            "name": "Upload pants.log",
            "uses": "actions/upload-artifact@v3",
            "if": "always()",
            "continue-on-error": True,
            "with": {
                "name": f"pants-log-{name.replace('/', '_')}-{self.platform_name()}",
                "path": ".pants.d/pants.log",
            },
        }


class RustTesting(Enum):
    NONE = "NONE"
    SOME = "SOME"  # Most tests.
    ALL = "ALL"  # All tests, lint and bench.


def bootstrap_jobs(
    helper: Helper,
    validate_ci_config: bool,
    rust_testing: RustTesting,
) -> Jobs:
    human_readable_job_name = "Bootstrap Pants"

    if rust_testing == RustTesting.NONE:
        human_readable_step_name = ""
        step_cmd = ""
    elif rust_testing == RustTesting.SOME:
        human_readable_job_name += ", test Rust"
        human_readable_step_name = "Test Rust"
        # We pass --tests to skip doc tests because our generated protos contain
        # invalid doc tests in their comments. We do not pass --all as BRFS tests don't
        # pass on GHA MacOS containers.
        step_cmd = helper.wrap_cmd(
            helper.maybe_append_cargo_test_parallelism("./cargo test --tests -- --nocapture")
        )
    elif rust_testing == RustTesting.ALL:
        human_readable_job_name += ", test and lint Rust"
        human_readable_step_name = "Test and lint Rust"
        # We pass --tests to skip doc tests because our generated protos contain
        # invalid doc tests in their comments.
        step_cmd = "\n".join(
            [
                "./build-support/bin/check_rust_pre_commit.sh",
                helper.maybe_append_cargo_test_parallelism(
                    "./cargo test --all --tests -- --nocapture"
                ),
                "./cargo check --benches",
                "./cargo doc",
            ]
        )
    else:
        raise ValueError(f"Unrecognized RustTesting value: {rust_testing}")

    if helper.platform in [Platform.LINUX_X86_64]:
        step_cmd = "sudo apt-get install -y pkg-config fuse libfuse-dev\n" + step_cmd
    human_readable_job_name += f" ({helper.platform_name()})"

    return {
        "name": human_readable_job_name,
        "runs-on": helper.runs_on(),
        "env": DISABLE_REMOTE_CACHE_ENV,
        "timeout-minutes": 60,
        "if": IS_PANTS_OWNER,
        "steps": [
            *helper.bootstrap_pants(),
            *(
                [
                    {
                        "name": "Validate CI config",
                        "run": dedent(
                            """\
                    ./pants run build-support/bin/generate_github_workflows.py -- --check
                    """
                        ),
                    }
                ]
                if validate_ci_config
                else []
            ),
            *(
                [
                    {
                        "name": human_readable_step_name,
                        # We pass --tests to skip doc tests because our generated protos contain
                        # invalid doc tests in their comments.
                        "run": step_cmd,
                        "env": {"TMPDIR": f"{gha_expr('runner.temp')}"},
                        "if": DONT_SKIP_RUST,
                    }
                ]
                if human_readable_step_name
                else []
            ),
        ],
    }


def test_jobs(helper: Helper, shard: str | None, platform_specific: bool) -> Jobs:
    human_readable_job_name = f"Test Python ({helper.platform_name()})"
    human_readable_step_name = "Run Python tests"
    log_name = "python-test"
    pants_args = ["test"]
    if shard:
        human_readable_job_name += f" Shard {shard}"
        human_readable_step_name = f"Run Python test shard {shard}"
        log_name += f"-{shard}"
        pants_args.append(f"--shard={shard}")
    pants_args.append("::")
    if platform_specific:
        pants_args = (
            ["--tag=+platform_specific_behavior"]
            + pants_args
            + ["--", "-m", "platform_specific_behavior"]
        )
    pants_args = ["./pants"] + pants_args
    pants_args_str = " ".join(pants_args) + "\n"

    return {
        "name": human_readable_job_name,
        "runs-on": helper.runs_on(),
        "needs": helper.job_name("bootstrap_pants"),
        "env": helper.platform_env(),
        "timeout-minutes": 90,
        "if": IS_PANTS_OWNER,
        "steps": [
            *checkout(),
            *launch_bazel_remote(),
            install_jdk(),
            *(
                [install_go(), download_apache_thrift()]
                if helper.platform == Platform.LINUX_X86_64
                # Other platforms either don't run those tests, or have the binaries
                # preinstalled on the self-hosted runners.
                else []
            ),
            *helper.setup_primary_python(),
            *helper.expose_all_pythons(),
            *helper.native_binaries_download(),
            {
                "name": human_readable_step_name,
                "run": pants_args_str,
            },
            helper.upload_log_artifacts(name=log_name),
        ],
    }


def linux_x86_64_test_jobs() -> Jobs:
    helper = Helper(Platform.LINUX_X86_64)

    def test_python_linux(shard: str) -> dict[str, Any]:
        return test_jobs(helper, shard, platform_specific=False)

    shard_name_prefix = helper.job_name("test_python")
    jobs = {
        helper.job_name("bootstrap_pants"): bootstrap_jobs(
            helper, validate_ci_config=True, rust_testing=RustTesting.ALL
        ),
        f"{shard_name_prefix}_0": test_python_linux("0/10"),
        f"{shard_name_prefix}_1": test_python_linux("1/10"),
        f"{shard_name_prefix}_2": test_python_linux("2/10"),
        f"{shard_name_prefix}_3": test_python_linux("3/10"),
        f"{shard_name_prefix}_4": test_python_linux("4/10"),
        f"{shard_name_prefix}_5": test_python_linux("5/10"),
        f"{shard_name_prefix}_6": test_python_linux("6/10"),
        f"{shard_name_prefix}_7": test_python_linux("7/10"),
        f"{shard_name_prefix}_8": test_python_linux("8/10"),
        f"{shard_name_prefix}_9": test_python_linux("9/10"),
    }
    return jobs


def linux_arm64_test_jobs() -> Jobs:
    helper = Helper(Platform.LINUX_ARM64)
    jobs = {
        helper.job_name("bootstrap_pants"): bootstrap_jobs(
            helper,
            validate_ci_config=False,
            rust_testing=RustTesting.SOME,
        ),
        helper.job_name("test_python"): test_jobs(helper, shard=None, platform_specific=True),
    }
    return jobs


def macos11_x86_64_test_jobs() -> Jobs:
    helper = Helper(Platform.MACOS11_X86_64)
    jobs = {
        helper.job_name("bootstrap_pants"): bootstrap_jobs(
            helper,
            validate_ci_config=False,
            rust_testing=RustTesting.SOME,
        ),
        helper.job_name("test_python"): test_jobs(helper, shard=None, platform_specific=True),
    }
    return jobs


def build_wheels_job(
    platform: Platform,
    for_deploy_ref: str | None,
    needs: list[str] | None,
) -> Jobs:
    helper = Helper(platform)
    # For manylinux compatibility, we build Linux wheels in a container rather than directly
    # on the Ubuntu runner. As a result, we have custom steps here to check out
    # the code, install rustup and expose Pythons.
    # TODO: Apply rust caching here.
    if platform == Platform.LINUX_X86_64:
        container = {"image": "quay.io/pypa/manylinux2014_x86_64:latest"}
    elif platform == Platform.LINUX_ARM64:
        # Unfortunately Equinix do not support the CentOS 7 image on the hardware we've been
        # generously given by the Works on ARM program. So we have to build in this image.
        container = {
            "image": "ghcr.io/pantsbuild/wheel_build_aarch64:v3-8384c5cf",
        }
    else:
        container = None

    if container:
        initial_steps = [
            *checkout(containerized=True, ref=for_deploy_ref),
            install_rustup(),
            {
                "name": "Expose Pythons",
                "run": dedent(
                    """\
                    echo "/opt/python/cp37-cp37m/bin" >> $GITHUB_PATH
                    echo "/opt/python/cp38-cp38/bin" >> $GITHUB_PATH
                    echo "/opt/python/cp39-cp39/bin" >> $GITHUB_PATH
                    """
                ),
            },
        ]
    else:
        initial_steps = [
            *checkout(ref=for_deploy_ref),
            *helper.expose_all_pythons(),
            # NB: We only cache Rust, but not `native_engine.so` and the Pants
            # virtualenv. This is because we must build both these things with
            # multiple Python versions, whereas that caching assumes only one primary
            # Python version (marked via matrix.strategy).
            *helper.rust_caches(),
        ]

    if_condition = (
        IS_PANTS_OWNER if for_deploy_ref else f"({IS_PANTS_OWNER}) && ({DONT_SKIP_WHEELS})"
    )
    return {
        helper.job_name("build_wheels"): {
            "if": if_condition,
            "name": f"Build wheels ({str(platform.value)})",
            "runs-on": helper.runs_on(),
            **({"container": container} if container else {}),
            **({"needs": needs} if needs else {}),
            "timeout-minutes": 90,
            "env": {
                **DISABLE_REMOTE_CACHE_ENV,
                # If we're not deploying these wheels, build in debug mode, which allows for
                # incremental compilation across wheels. If this becomes too slow in CI, most likely
                # the answer will be to adjust the `opt-level` for the relevant Cargo profile rather
                # than to not use debug mode.
                **({} if for_deploy_ref else {"MODE": "debug"}),
            },
            "steps": [
                *initial_steps,
                *([] if platform == Platform.LINUX_ARM64 else [install_go()]),
                *helper.build_wheels(),
                helper.upload_log_artifacts(name="wheels"),
                *([deploy_to_s3("Deploy wheels to S3")] if for_deploy_ref else []),
            ],
        },
    }


def build_wheels_jobs(*, for_deploy_ref: str | None = None, needs: list[str] | None = None) -> Jobs:
    # N.B.: When altering the number of total wheels built, please edit the expected
    # total in the release.py script. Currently here:
    return {
        **build_wheels_job(Platform.LINUX_X86_64, for_deploy_ref, needs),
        **build_wheels_job(Platform.LINUX_ARM64, for_deploy_ref, needs),
        **build_wheels_job(Platform.MACOS10_15_X86_64, for_deploy_ref, needs),
        **build_wheels_job(Platform.MACOS11_ARM64, for_deploy_ref, needs),
    }


def test_workflow_jobs() -> Jobs:
    linux_x86_64_helper = Helper(Platform.LINUX_X86_64)
    jobs: dict[str, Any] = {
        "check_labels": {
            "name": "Ensure PR has a category label",
            "runs-on": linux_x86_64_helper.runs_on(),
            "if": IS_PANTS_OWNER,
            "steps": ensure_category_label(),
        },
    }
    jobs.update(**linux_x86_64_test_jobs())
    jobs.update(**linux_arm64_test_jobs())
    jobs.update(**macos11_x86_64_test_jobs())
    jobs.update(**build_wheels_jobs())
    jobs.update(
        {
            "lint_python": {
                "name": "Lint Python and Shell",
                "runs-on": linux_x86_64_helper.runs_on(),
                "needs": "bootstrap_pants_linux_x86_64",
                "timeout-minutes": 30,
                "if": IS_PANTS_OWNER,
                "steps": [
                    *checkout(),
                    *launch_bazel_remote(),
                    *linux_x86_64_helper.setup_primary_python(),
                    *linux_x86_64_helper.native_binaries_download(),
                    {
                        "name": "Lint",
                        "run": "./pants lint check ::\n",
                    },
                    linux_x86_64_helper.upload_log_artifacts(name="lint"),
                ],
            },
        }
    )
    return jobs


@dataclass(frozen=True)
class WorkflowInput:
    name: str
    type_str: str
    default: str | int | None = None


def workflow_dispatch_inputs(
    workflow_inputs: Sequence[WorkflowInput],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Builds `on.workflow_dispatch.inputs` and a corresponding `env` section to consume them."""
    inputs = {
        wi.name.lower(): {
            "required": (wi.default is None),
            "type": wi.type_str,
            **({} if wi.default is None else {"default": wi.default}),
        }
        for wi in workflow_inputs
    }
    env = {wi.name: gha_expr("github.event.inputs." + wi.name.lower()) for wi in workflow_inputs}
    return inputs, env


def cache_comparison_jobs_and_inputs() -> tuple[Jobs, dict[str, Any]]:
    cc_inputs, cc_env = workflow_dispatch_inputs(
        [
            WorkflowInput(
                "PANTS_ARGS",
                "string",
                default="check lint test ::",
            ),
            WorkflowInput(
                "BASE_REF",
                "string",
                default="main",
            ),
            WorkflowInput(
                "BUILD_COMMIT",
                "string",
            ),
            WorkflowInput(
                "SOURCE_DIFFSPEC",
                "string",
            ),
            WorkflowInput(
                "SOURCE_DIFFSPEC_STEP",
                "int",
                default=1,
            ),
        ]
    )

    helper = Helper(Platform.LINUX_X86_64)

    jobs = {
        "cache_comparison": {
            "runs-on": "ubuntu-latest",
            "timeout-minutes": 90,
            "steps": [
                *checkout(),
                *helper.setup_primary_python(),
                *helper.expose_all_pythons(),
                {
                    "name": "Prepare cache comparison",
                    "run": dedent(
                        # NB: The fetch depth is arbitrary, but is meant to capture the
                        # most likely `diffspecs` used as arguments.
                        """\
                        MODE=debug ./pants package build-support/bin/cache_comparison.py
                        git fetch --no-tags --depth=1024 origin "$BASE_REF"
                        """
                    ),
                    "env": cc_env,
                },
                {
                    "name": "Run cache comparison",
                    "run": dedent(
                        """\
                        dist/build-support.bin/cache_comparison_py.pex \\
                          --args="$PANTS_ARGS" \\
                          --build-commit="$BUILD_COMMIT" \\
                          --source-diffspec="$SOURCE_DIFFSPEC" \\
                          --source-diffspec-step=$SOURCE_DIFFSPEC_STEP
                        """
                    ),
                    "env": cc_env,
                },
            ],
        }
    }

    return jobs, cc_inputs


def release_jobs_and_inputs() -> tuple[Jobs, dict[str, Any]]:
    """Builds and releases a git ref to S3, and (if the ref is a release tag) to PyPI."""
    inputs, env = workflow_dispatch_inputs([WorkflowInput("REF", "string")])

    pypi_release_dir = "dest/pypi_release"
    helper = Helper(Platform.LINUX_X86_64)
    wheels_jobs = build_wheels_jobs(
        needs=["determine_ref"], for_deploy_ref=gha_expr("needs.determine_ref.outputs.build-ref")
    )
    wheels_job_names = tuple(wheels_jobs.keys())
    jobs = {
        "determine_ref": {
            "name": "Determine the ref to build",
            "runs-on": "ubuntu-latest",
            "if": IS_PANTS_OWNER,
            "steps": [
                {
                    "name": "Determine ref to build",
                    "env": env,
                    "id": "determine_ref",
                    "run": dedent(
                        """\
                        if [[ -n "$REF" ]]; then
                            ref="$REF"
                        else
                            ref="${GITHUB_REF#refs/tags/}"
                        fi
                        echo "build-ref=${ref}" >> $GITHUB_OUTPUT
                        if [[ "${ref}" =~ ^release_.+$ ]]; then
                            echo "is-release=true" >> $GITHUB_OUTPUT
                        fi
                        """
                    ),
                },
            ],
            "outputs": {
                "build-ref": gha_expr("steps.determine_ref.outputs.build-ref"),
                "is-release": gha_expr("steps.determine_ref.outputs.is-release"),
            },
        },
        **wheels_jobs,
        "publish": {
            "runs-on": "ubuntu-latest",
            "needs": [*wheels_job_names, "determine_ref"],
            "if": f"{IS_PANTS_OWNER} && needs.determine_ref.outputs.is-release == 'true'",
            "steps": [
                {
                    "name": "Checkout Pants at Release Tag",
                    "uses": "actions/checkout@v3",
                    "with": {"ref": f"{gha_expr('needs.determine_ref.outputs.build-ref')}"},
                },
                *helper.setup_primary_python(),
                *helper.expose_all_pythons(),
                {
                    "name": "Fetch and stabilize wheels",
                    "run": f"./pants run build-support/bin/release.py -- fetch-and-stabilize --dest={pypi_release_dir}",
                    "env": {
                        # This step does not actually build anything: only download wheels from S3.
                        "MODE": "debug",
                    },
                },
                {
                    "name": "Create Release -> Commit Mapping",
                    # The `git rev-parse` subshell below is used to obtain the tagged commit sha.
                    # The syntax it uses is tricky, but correct. The literal suffix `^{commit}` gets
                    # the sha of the commit object that is the tag's target (as opposed to the sha
                    # of the tag object itself). Due to Python f-strings, the nearness of shell
                    # ${VAR} syntax to it and the ${{ github }} syntax ... this is a confusing read.
                    "run": dedent(
                        f"""\
                        tag="{gha_expr("needs.determine_ref.outputs.build-ref")}"
                        commit="$(git rev-parse ${{tag}}^{{commit}})"

                        echo "Recording tag ${{tag}} is of commit ${{commit}}"
                        mkdir -p dist/deploy/tags/pantsbuild.pants
                        echo "${{commit}}" > "dist/deploy/tags/pantsbuild.pants/${{tag}}"
                        """
                    ),
                },
                {
                    "name": "Publish to PyPI",
                    "uses": "pypa/gh-action-pypi-publish@release/v1",
                    "with": {
                        "password": gha_expr("secrets.PANTSBUILD_PYPI_API_TOKEN"),
                        "packages-dir": pypi_release_dir,
                        "skip-existing": True,
                    },
                },
                deploy_to_s3(
                    "Deploy commit mapping to S3",
                    scope="tags/pantsbuild.pants",
                ),
            ],
        },
    }

    return jobs, inputs


# ----------------------------------------------------------------------
# Main file
# ----------------------------------------------------------------------


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generates github workflow YAML.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check that the files match rather than re-generating them.",
    )
    return parser


# PyYAML will try by default to use anchors to deduplicate certain code. The alias
# names are cryptic, though, like `&id002`, so we turn this feature off.
class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def merge_ok(pr_jobs: list[str]) -> Jobs:
    # Generate the "Merge OK" job that branch protection can monitor.
    # Note: A job skipped due to an "if" condition, or due to a failed dependency, counts as
    # successful (!) for the purpose of branch protection. Therefore we can't have the "Merge OK"
    # job depend directly on the other jobs - it will always be successful.
    # So instead we have a "Set merge OK" job to set an output that the "Merge OK" job can act on,
    # and we check for that job in branch protection.  Only a truly successful (non-skipped)
    # job will actually set that output.
    return {
        "set_merge_ok": {
            "name": "Set Merge OK",
            "runs-on": Helper(Platform.LINUX_X86_64).runs_on(),
            # NB: This always() condition is critical, as it ensures that this job is run even if
            #   jobs it depends on are skipped.
            "if": "always() && !contains(needs.*.result, 'failure') && !contains(needs.*.result, 'cancelled')",
            "needs": ["classify_changes", "check_labels"] + sorted(pr_jobs),
            "outputs": {"merge_ok": f"{gha_expr('steps.set_merge_ok.outputs.merge_ok')}"},
            "steps": [
                {
                    "id": "set_merge_ok",
                    "run": "echo 'merge_ok=true' >> ${GITHUB_OUTPUT}",
                },
            ],
        },
        "merge_ok": {
            "name": "Merge OK",
            "runs-on": Helper(Platform.LINUX_X86_64).runs_on(),
            # NB: This always() condition is critical, as it ensures that this job is never
            # skipped (if it were skipped it would be treated as vacuously successful by branch protection).
            "if": "always()",
            "needs": ["set_merge_ok"],
            "steps": [
                {
                    "run": dedent(
                        f"""\
                merge_ok="{gha_expr('needs.set_merge_ok.outputs.merge_ok')}"
                if [[ "${{merge_ok}}" == "true" ]]; then
                    echo "Merge OK"
                    exit 0
                else
                    echo "Merge NOT OK"
                    exit 1
                fi
                """
                    )
                }
            ],
        },
    }


def generate() -> dict[Path, str]:
    """Generate all YAML configs with repo-relative paths."""

    pr_jobs = test_workflow_jobs()
    pr_jobs.update(**classify_changes())
    for key, val in pr_jobs.items():
        if key in {"check_labels", "classify_changes"}:
            continue
        needs = val.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        needs.extend(["classify_changes"])
        val["needs"] = needs
        if_cond = val.get("if")
        not_docs_only = "needs.classify_changes.outputs.docs_only != 'true'"
        val["if"] = not_docs_only if if_cond is None else f"({if_cond}) && ({not_docs_only})"
    pr_jobs.update(merge_ok(sorted(pr_jobs.keys())))

    test_workflow_name = "Pull Request CI"
    test_yaml = yaml.dump(
        {
            "name": test_workflow_name,
            "concurrency": {
                "group": "${{ github.workflow }}-${{ github.event.pull_request.number || github.sha }}",
                "cancel-in-progress": True,
            },
            "on": {"pull_request": {}, "push": {"branches": ["main", "2.*.x"]}},
            "jobs": pr_jobs,
            "env": global_env(),
        },
        width=120,
        Dumper=NoAliasDumper,
    )

    ignore_advisories = " ".join(
        f"--ignore {adv_id}" for adv_id in CARGO_AUDIT_IGNORED_ADVISORY_IDS
    )
    audit_yaml = yaml.dump(
        {
            "name": "Cargo Audit",
            "on": {
                # 08:11 UTC / 12:11AM PST, 1:11AM PDT: arbitrary time after hours.
                "schedule": [{"cron": "11 8 * * *"}],
                # Allow manually triggering this workflow
                "workflow_dispatch": None,
            },
            "jobs": {
                "audit": {
                    "runs-on": "ubuntu-latest",
                    "if": IS_PANTS_OWNER,
                    "steps": [
                        *checkout(),
                        {
                            "name": "Cargo audit (for security vulnerabilities)",
                            "run": f"./cargo install --version 0.17.5 cargo-audit\n./cargo audit {ignore_advisories}\n",
                        },
                    ],
                }
            },
        }
    )

    cc_jobs, cc_inputs = cache_comparison_jobs_and_inputs()
    cache_comparison_yaml = yaml.dump(
        {
            "name": "Cache Comparison",
            # Kicked off manually.
            "on": {"workflow_dispatch": {"inputs": cc_inputs}},
            "jobs": cc_jobs,
        },
        Dumper=NoAliasDumper,
    )

    release_jobs, release_inputs = release_jobs_and_inputs()
    release_yaml = yaml.dump(
        {
            "name": "Release",
            "on": {
                "push": {"tags": ["release_*"]},
                "workflow_dispatch": {"inputs": release_inputs},
            },
            "jobs": release_jobs,
        },
        Dumper=NoAliasDumper,
    )

    return {
        Path(".github/workflows/audit.yaml"): f"{HEADER}\n\n{audit_yaml}",
        Path(".github/workflows/cache_comparison.yaml"): f"{HEADER}\n\n{cache_comparison_yaml}",
        Path(".github/workflows/test.yaml"): f"{HEADER}\n\n{test_yaml}",
        Path(".github/workflows/release.yaml"): f"{HEADER}\n\n{release_yaml}",
    }


def main() -> None:
    args = create_parser().parse_args()
    generated_yaml = generate()
    if args.check:
        for path, content in generated_yaml.items():
            if path.read_text() != content:
                die(
                    dedent(
                        f"""\
                        Error: Generated path mismatched: {path}
                        To re-generate, run: `./pants run build-support/bin/{
                            os.path.basename(__file__)
                        }`
                        """
                    )
                )
    else:
        for path, content in generated_yaml.items():
            path.write_text(content)


if __name__ == "__main__":
    main()
