# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import difflib
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from textwrap import dedent  # noqa: PNT20
from typing import Any, Dict, Sequence, cast

import toml
import yaml
from pants_release.common import die

from pants.util.strutil import softwrap

HEADER = dedent(
    """\
    # GENERATED, DO NOT EDIT!
    # To change, edit `src/python/pants_release/generate_github_workflows.py` and run:
    #   ./pants run src/python/pants_release/generate_github_workflows.py
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
    *,
    fetch_depth: int = 250,
    containerized: bool = False,
    ref: str | None = None,
    **extra_opts: object,
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
                **extra_opts,
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
    """Run a sidecar bazel-remote instance.

    This process proxies to a public-read/private-write S3 bucket (cache.pantsbuild.org). PRs within
    pantsbuild/pants will have AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY secrets set and so will be
    able to read and write the cache. PRs across forks will not, so they use hard-coded read only
    creds so they can at least read from the cache.
    """
    return [
        {
            "name": "Launch bazel-remote",
            "run": dedent(
                """\
                mkdir -p ~/bazel-remote
                if [[ -z "${AWS_ACCESS_KEY_ID}" ]]; then
                  CACHE_WRITE=false
                  # If no secret read/write creds, use hard-coded read-only creds, so that
                  # cross-fork PRs can at least read from the cache.
                  # These creds are hard-coded here in this public repo, which makes the bucket
                  # world-readable. But since putting raw AWS tokens in a public repo, even
                  # deliberately, is icky, we base64-them. This will at least help hide from
                  # automated scanners that look for checked in AWS keys.
                  # Not that it would be terrible if we were scanned, since this is public
                  # on purpose, but it's best not to draw attention.
                  AWS_ACCESS_KEY_ID=$(echo 'QUtJQVY2QTZHN1JRVkJJUVM1RUEK' | base64 -d)
                  AWS_SECRET_ACCESS_KEY=$(echo 'd3dOQ1k1eHJJWVVtejZBblV6M0l1endXV0loQWZWcW9GZlVjMDlKRwo=' | base64 -d)
                else
                  CACHE_WRITE=true
                fi
                docker run --detach -u 1001:1000 \
                  -v ~/bazel-remote:/data \
                  -p 9092:9092 \
                  buchgr/bazel-remote-cache:v2.4.1 \
                  --s3.auth_method=access_key \
                  --s3.access_key_id="${AWS_ACCESS_KEY_ID}" \
                  --s3.secret_access_key="${AWS_SECRET_ACCESS_KEY}" \
                  --s3.bucket=cache.pantsbuild.org \
                  --s3.endpoint=s3.us-east-1.amazonaws.com \
                  --max_size 30
                echo "PANTS_REMOTE_STORE_ADDRESS=grpc://localhost:9092" >> "$GITHUB_ENV"
                echo "PANTS_REMOTE_CACHE_READ=true" >> "$GITHUB_ENV"
                echo "PANTS_REMOTE_CACHE_WRITE=${CACHE_WRITE}" >> "$GITHUB_ENV"
                """
            ),
            "env": {
                "AWS_ACCESS_KEY_ID": f"{gha_expr('secrets.AWS_ACCESS_KEY_ID')}",
                "AWS_SECRET_ACCESS_KEY": f"{gha_expr('secrets.AWS_SECRET_ACCESS_KEY')}",
            },
        }
    ]


def global_env() -> Env:
    return {
        "PANTS_CONFIG_FILES": "+['pants.ci.toml']",
        "RUST_BACKTRACE": "all",
    }


def rust_channel() -> str:
    with open("src/rust/engine/rust-toolchain") as fp:
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


def install_python(version: str) -> Step:
    return {
        "name": f"Set up Python {version}",
        "uses": "actions/setup-python@v4",
        "with": {"python-version": version},
    }


def install_node(version: str) -> Step:
    return {
        "name": f"Set up Node {version}",
        "uses": "actions/setup-node@v3",
        "with": {"node-version": version},
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


# NOTE: Any updates to the version of arduino/setup-protoc will require an audit of the updated  source code to verify
# nothing "bad" has been added to the action. (We pass the user's GitHub secret to the action in order to avoid the
# default GitHub rate limits when downloading protoc._
def install_protoc() -> Step:
    return {
        "name": "Install Protoc",
        "uses": "arduino/setup-protoc@9b1ee5b22b0a3f1feb8c2ff99b32c89b3c3191e9",
        "with": {
            "version": "23.x",
            "repo-token": "${{ secrets.GITHUB_TOKEN }}",
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
        if self.platform == Platform.LINUX_X86_64:
            # Currently we run Linux x86_64 CI on GitHub Actions-hosted hardware, and
            # these are weak dual-core machines. Default parallelism on those machines
            # leads to many test timeouts. This parallelism reduction appears to lead
            # to test shard runs that are 50% slower on average, but more likely to
            # complete without timeouts.
            # TODO: If we add a "redo timed out tests" feature, we can kill this.
            ret["PANTS_PROCESS_EXECUTION_LOCAL_PARALLELISM"] = "1"
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
            install_protoc(),  # for `prost` crate
            {
                "name": "Set rustup profile",
                "run": "rustup set profile default",
            },
            {
                "name": "Cache Rust toolchain",
                "uses": "actions/cache@v3",
                "with": {
                    "path": f"~/.rustup/toolchains/{rust_channel()}-*\n~/.rustup/update-hashes\n~/.rustup/settings.toml\n",
                    "key": f"{self.platform_name()}-rustup-{hash_files('src/rust/engine/rust-toolchain')}-v2",
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
            ret.append(install_python(PYTHON_VERSION))
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

    def upload_log_artifacts(self, name: str) -> Step:
        return {
            "name": "Upload pants.log",
            "uses": "actions/upload-artifact@v3",
            "if": "always()",
            "continue-on-error": True,
            "with": {
                "name": f"logs-{name.replace('/', '_')}-{self.platform_name()}",
                "path": ".pants.d/workdir/*.log",
            },
        }

    def upload_test_reports(self) -> Step:
        # The path doesn't include job ID, as we want to aggregate test reports across all
        # jobs/shards in a workflow.  We do, however, qualify by run attempt, so we capture
        # separate reports for tests that flake between attempts on the same workflow run.
        s3_dst = (
            "s3://logs.pantsbuild.org/test/reports/"
            + self.platform_name()
            + "/"
            + "$(git show --no-patch --format=%cd --date=format:%Y-%m-%d)/"
            + "${GITHUB_REF_NAME//\\//_}/${GITHUB_RUN_ID}/${GITHUB_RUN_ATTEMPT}/${GITHUB_JOB}"
        )
        return {
            "name": "Upload test reports",
            "if": "always()",
            "continue-on-error": True,
            "run": dedent(
                f"""\
                export S3_DST={s3_dst}
                echo "Uploading test reports to ${{S3_DST}}"
                ./pants run ./src/python/pants_release/copy_to_s3.py \
                  -- \
                  --src-prefix=dist/test/reports \
                  --dst-prefix=${{S3_DST}} \
                  --path=""
                """
            ),
            "env": {
                "AWS_SECRET_ACCESS_KEY": f"{gha_expr('secrets.AWS_SECRET_ACCESS_KEY')}",
                "AWS_ACCESS_KEY_ID": f"{gha_expr('secrets.AWS_ACCESS_KEY_ID')}",
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
            helper.maybe_append_cargo_test_parallelism(
                "./cargo test --locked --tests -- --nocapture"
            )
        )
    elif rust_testing == RustTesting.ALL:
        human_readable_job_name += ", test and lint Rust"
        human_readable_step_name = "Test and lint Rust"
        # We pass --tests to skip doc tests because our generated protos contain
        # invalid doc tests in their comments, and --benches to ensure that the
        # benchmarks can at least execute once correctly
        step_cmd = "\n".join(
            [
                "./build-support/bin/check_rust_pre_commit.sh",
                helper.maybe_append_cargo_test_parallelism(
                    "./cargo test --locked --all --tests --benches -- --nocapture"
                ),
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
                    ./pants run src/python/pants_release/generate_github_workflows.py -- --check
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


def test_jobs(
    helper: Helper, shard: str | None, platform_specific: bool, with_remote_caching: bool
) -> Jobs:
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
            *(launch_bazel_remote() if with_remote_caching else []),
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
            helper.upload_test_reports(),
            helper.upload_log_artifacts(name=log_name),
        ],
    }


def linux_x86_64_test_jobs() -> Jobs:
    helper = Helper(Platform.LINUX_X86_64)

    def test_python_linux(shard: str) -> dict[str, Any]:
        return test_jobs(helper, shard, platform_specific=False, with_remote_caching=True)

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
        # We run these on a dedicated host with ample local cache, so remote caching
        # just adds cost but little value.
        helper.job_name("test_python"): test_jobs(
            helper, shard=None, platform_specific=True, with_remote_caching=False
        ),
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
        # We run these on a dedicated host with ample local cache, so remote caching
        # just adds cost but little value.
        helper.job_name("test_python"): test_jobs(
            helper, shard=None, platform_specific=True, with_remote_caching=False
        ),
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
                install_protoc(),  # for prost crate
                *([] if platform == Platform.LINUX_ARM64 else [install_go()]),
                {
                    "name": "Build wheels",
                    "run": "./pants run src/python/pants_release/release.py -- build-wheels",
                    "env": helper.platform_env(),
                },
                {
                    "name": "Build Pants PEX",
                    "run": "./pants package src/python/pants:pants-pex",
                    "env": helper.platform_env(),
                },
                helper.upload_log_artifacts(name="wheels-and-pex"),
                *(
                    [
                        {
                            "name": "Upload Wheel and Pex",
                            "if": "needs.release_info.outputs.is-release == 'true'",
                            # NB: We can't use `gh` or even `./pants run 3rdparty/tools/gh` reliably
                            #   in this job. Certain variations run on docker images without `gh`,
                            #   and we could be building on a tag that doesn't have the `pants run <gh>`
                            #   support. `curl` is a good lowest-common-denominator way to upload the assets.
                            "run": dedent(
                                """\
                                PANTS_VER=$(PEX_INTERPRETER=1 dist/src.python.pants/pants-pex.pex -c "import pants.version;print(pants.version.VERSION)")
                                PY_VER=$(PEX_INTERPRETER=1 dist/src.python.pants/pants-pex.pex -c "import sys;print(f'cp{sys.version_info[0]}{sys.version_info[1]}')")
                                PLAT=$(PEX_INTERPRETER=1 dist/src.python.pants/pants-pex.pex -c "import os;print(f'{os.uname().sysname.lower()}_{os.uname().machine.lower()}')")
                                PEX_FILENAME=pants.$PANTS_VER-$PY_VER-$PLAT.pex

                                mv dist/src.python.pants/pants-pex.pex dist/src.python.pants/$PEX_FILENAME

                                curl -L --fail \\
                                    -X POST \\
                                    -H "Authorization: Bearer ${{ github.token }}" \\
                                    -H "Content-Type: application/octet-stream" \\
                                    ${{ needs.release_info.outputs.release-asset-upload-url }}?name=$PEX_FILENAME \\
                                    --data-binary "@dist/src.python.pants/$PEX_FILENAME"

                                WHL=$(find dist/deploy/wheels/pantsbuild.pants -type f -name "pantsbuild.pants-*.whl")
                                curl -L --fail \\
                                    -X POST \\
                                    -H "Authorization: Bearer ${{ github.token }}" \\
                                    -H "Content-Type: application/octet-stream" \\
                                    "${{ needs.release_info.outputs.release-asset-upload-url }}?name=$(basename $WHL)" \\
                                    --data-binary "@$WHL";
                                """
                            ),
                        },
                        *(
                            [
                                {
                                    "name": "Upload testutil Wheel",
                                    "if": "needs.release_info.outputs.is-release == 'true'",
                                    # NB: See above about curl
                                    "run": dedent(
                                        """\
                                        WHL=$(find dist/deploy/wheels/pantsbuild.pants -type f -name "pantsbuild.pants.testutil*.whl")
                                        curl -L --fail \\
                                            -X POST \\
                                            -H "Authorization: Bearer ${{ github.token }}" \\
                                            -H "Content-Type: application/octet-stream" \\
                                            "${{ needs.release_info.outputs.release-asset-upload-url }}?name=$(basename $WHL)" \\
                                            --data-binary "@$WHL";
                                """
                                    ),
                                },
                            ]
                            if platform == Platform.LINUX_X86_64
                            else []
                        ),
                    ]
                    if for_deploy_ref
                    else []
                ),
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
    description: None | str = None


def workflow_dispatch_inputs(
    workflow_inputs: Sequence[WorkflowInput],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Builds `on.workflow_dispatch.inputs` and a corresponding `env` section to consume them."""
    inputs = {
        wi.name.lower(): {
            "required": (wi.default is None),
            "type": wi.type_str,
            **({} if wi.description is None else {"description": wi.description}),
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
    inputs, env = workflow_dispatch_inputs([WorkflowInput("REF", "string")])

    helper = Helper(Platform.LINUX_X86_64)
    wheels_jobs = build_wheels_jobs(
        needs=["release_info"], for_deploy_ref=gha_expr("needs.release_info.outputs.build-ref")
    )
    wheels_job_names = tuple(wheels_jobs.keys())
    jobs = {
        "release_info": {
            "name": "Create draft release and output info",
            "runs-on": "ubuntu-latest",
            "if": IS_PANTS_OWNER,
            "steps": [
                {
                    "name": "Determine ref to build",
                    "env": env,
                    "id": "get_info",
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
                {
                    "name": "Make GitHub Release",
                    "id": "make_draft_release",
                    "if": f"{IS_PANTS_OWNER} && steps.get_info.outputs.is-release == 'true'",
                    "env": {
                        "GH_TOKEN": "${{ github.token }}",
                        "GH_REPO": "${{ github.repository }}",
                    },
                    "run": dedent(
                        """\
                        RELEASE_TAG=${{ steps.get_info.outputs.build-ref }}
                        RELEASE_VERSION="${RELEASE_TAG#release_}"

                        # NB: This could be a re-run of a release, in the event a job/step failed.
                        if ! gh release view $RELEASE_TAG ; then
                            GH_RELEASE_ARGS=("--notes" "")
                            GH_RELEASE_ARGS+=("--title" "$RELEASE_TAG")
                            if [[ $RELEASE_VERSION =~ [[:alpha:]] ]]; then
                                GH_RELEASE_ARGS+=("--prerelease")
                                GH_RELEASE_ARGS+=("--latest=false")
                            else
                                STABLE_RELEASE_TAGS=$(gh api -X GET -F per_page=100 /repos/{owner}/{repo}/releases --jq '.[].tag_name | sub("^release_"; "") | select(test("^[0-9.]+$"))')
                                LATEST_TAG=$(echo "$STABLE_RELEASE_TAGS $RELEASE_TAG" | tr ' ' '\\n' | sort --version-sort | tail -n 1)
                                if [[ $RELEASE_TAG == $LATEST_TAG ]]; then
                                    GH_RELEASE_ARGS+=("--latest=true")
                                else
                                    GH_RELEASE_ARGS+=("--latest=false")
                                fi
                            fi

                            gh release create "$RELEASE_TAG" "${GH_RELEASE_ARGS[@]}" --draft
                        fi

                        ASSET_UPLOAD_URL=$(gh release view "$RELEASE_TAG" --json uploadUrl --jq '.uploadUrl | sub("\\\\{\\\\?.*$"; "")')
                        echo "release-asset-upload-url=$ASSET_UPLOAD_URL" >> $GITHUB_OUTPUT
                        """
                    ),
                },
            ],
            "outputs": {
                "build-ref": gha_expr("steps.get_info.outputs.build-ref"),
                "release-asset-upload-url": gha_expr(
                    "steps.make_draft_release.outputs.release-asset-upload-url"
                ),
                "is-release": gha_expr("steps.get_info.outputs.is-release"),
            },
        },
        **wheels_jobs,
        "publish": {
            "runs-on": "ubuntu-latest",
            "needs": [*wheels_job_names, "release_info"],
            "if": f"{IS_PANTS_OWNER} && needs.release_info.outputs.is-release == 'true'",
            "env": {
                # This job does not actually build anything: only download wheels from S3.
                "MODE": "debug",
            },
            "steps": [
                {
                    "name": "Checkout Pants at Release Tag",
                    "uses": "actions/checkout@v3",
                    "with": {
                        # N.B.: We need the last few edits to VERSION. Instead of guessing, just
                        # clone the repo, we're not so big as to need to optimize this.
                        "fetch-depth": "0",
                        "ref": f"{gha_expr('needs.release_info.outputs.build-ref')}",
                        "fetch-tags": True,
                    },
                },
                *helper.setup_primary_python(),
                *helper.expose_all_pythons(),
                *helper.bootstrap_caches(),
                {
                    "name": "Generate announcement",
                    "run": dedent(
                        """\
                        ./pants run src/python/pants_release/generate_release_announcement.py \
                        -- --output-dir=${{ runner.temp }}
                        """
                    ),
                },
                {
                    "name": "Announce to Slack",
                    "uses": "slackapi/slack-github-action@v1.24.0",
                    "with": {
                        "channel-id": "C18RRR4JK",
                        "payload-file-path": "${{ runner.temp }}/slack_announcement.json",
                    },
                    "env": {"SLACK_BOT_TOKEN": f"{gha_expr('secrets.SLACK_BOT_TOKEN')}"},
                },
                {
                    "name": "Announce to pants-devel",
                    "uses": "dawidd6/action-send-mail@v3.8.0",
                    "with": {
                        # Note: Email is sent from the dedicated account pants.announce@gmail.com.
                        # The EMAIL_CONNECTION_URL should be of the form:
                        # smtp+starttls://pants.announce@gmail.com:password@smtp.gmail.com:465
                        # (i.e., should use gmail's raw SMTP server), and the password
                        # should be a Google account "app password" set up for this purpose
                        # (not the Google account's regular password).
                        # And, of course, that account must have permission to post to pants-devel.
                        "connection_url": f"{gha_expr('secrets.EMAIL_CONNECTION_URL')}",
                        "secure": True,
                        "subject": "file://${{ runner.temp }}/email_announcement_subject.txt",
                        "to": "pants-devel@googlegroups.com",
                        "from": "Pants Announce",
                        "body": "file://${{ runner.temp }}/email_announcement_body.md",
                        "convert_markdown": True,
                    },
                },
                {
                    "name": "Get release notes",
                    "run": dedent(
                        """\
                        ./pants run src/python/pants_release/changelog.py -- "${{ needs.release_info.outputs.build-ref }}" > notes.txt
                        """
                    ),
                    "env": {
                        "GH_TOKEN": "${{ github.token }}",
                        "GH_REPO": "${{ github.repository }}",
                    },
                },
                {
                    "name": "Publish GitHub Release",
                    "env": {
                        "GH_TOKEN": "${{ github.token }}",
                        "GH_REPO": "${{ github.repository }}",
                    },
                    "run": dedent(
                        f"""\
                        gh release edit {gha_expr("needs.release_info.outputs.build-ref") } --draft=false --notes-file notes.txt
                        """
                    ),
                },
                {
                    "name": "Trigger cheeseshop build",
                    "env": {
                        "GH_TOKEN": "${{ secrets.WORKER_PANTS_CHEESESHOP_TRIGGER_PAT }}",
                    },
                    "run": dedent(
                        """\
                        gh api -X POST "/repos/pantsbuild/wheels.pantsbuild.org/dispatches" -F event_type=github-pages
                        """
                    ),
                },
                {
                    "name": "Trigger docs sync",
                    "if": "needs.release_info.outputs.is-release == 'true'",
                    "env": {
                        "GH_TOKEN": "${{ secrets.WORKER_PANTS_PANTSBUILD_ORG_TRIGGER_PAT }}",
                    },
                    "run": dedent(
                        """\
                        RELEASE_TAG=${{ needs.release_info.outputs.build-ref }}
                        RELEASE_VERSION="${RELEASE_TAG#release_}"
                        gh workflow run sync_docs.yml -F "version=$RELEASE_VERSION" -F "reviewer=${{ github.actor }}" -R pantsbuild/pantsbuild.org
                        """
                    ),
                },
            ],
        },
    }

    return jobs, inputs


class DefaultGoals(str, Enum):
    tailor_update_build_files = "tailor --check update-build-files --check ::"
    lint_check = "lint check ::"
    test = "test ::"
    package = "package ::"


@dataclass
class Repo:
    """A specification for an external public repository to run pants' testing against.

    Each repository is tested in two configurations:

    1. using the repository's default configuration (pants version, no additional settings), as a baseline

    2. overriding the pants version and potentially setting additional `PANTS_...` environment
       variable settings (both specified as workflow inputs)

    The second is the interesting test, to validate whether a particular version/configuration of
    Pants runs against this repository. The first/baseline is to make it obvious if the behaviour
    _changes_, to avoid trying to analyse problems that already exist upstream.
    """

    name: str
    """
    `user/repo`, referring to `https://github.com/user/repo`. (This can be expanded to other services, if required.)
    """

    python_version: str = "3.10"
    """
    The Python version to install system-wide for user code to use.
    """

    env: dict[str, str] = field(default_factory=dict)
    """
    Any extra environment variables to provide to all pants steps
    """

    install_go: bool = False
    """
    Whether to install Go system-wide
    """

    install_thrift: bool = False
    """
    Whether to install Thrift system-wide
    """

    node_version: None | str = None
    """
    Whether to install Node/NPM system-wide, and which version if so
    """

    checkout_options: dict[str, Any] = field(default_factory=dict)
    """
    Any additional options to provide to actions/checkout
    """

    setup_commands: str = ""
    """
    Any additional set-up commands to run before pants (e.g. `sudo apt install ...`)
    """

    goals: Sequence[str] = tuple(DefaultGoals)
    """
    Which pants goals to run, e.g. `goals=["test some/dir::"]` would only run `pants test some/dir::`
    """


PUBLIC_REPOS = [
    # pants' examples
    Repo(
        name="pantsbuild/example-adhoc",
        node_version="20",
        goals=[
            # TODO: https://github.com/pantsbuild/pants/issues/14492 means pants can't find the
            # `setup-node`-installed node, so we have to exclude `package ::`
            DefaultGoals.lint_check,
            DefaultGoals.test,
        ],
    ),
    Repo(name="pantsbuild/example-codegen", install_thrift=True),
    Repo(name="pantsbuild/example-django", python_version="3.9"),
    Repo(
        name="pantsbuild/example-docker",
        python_version="3.8",
        env={"DYNAMIC_TAG": "dynamic-tag-here"},
    ),
    Repo(name="pantsbuild/example-golang", install_go=True),
    Repo(name="pantsbuild/example-jvm"),
    Repo(name="pantsbuild/example-kotlin"),
    Repo(name="pantsbuild/example-python", python_version="3.9"),
    Repo(
        name="pantsbuild/example-visibility",
        python_version="3.9",
        # skip check
        goals=[DefaultGoals.tailor_update_build_files, "lint ::", DefaultGoals.test],
    ),
    # other pants' managed repos
    Repo(name="pantsbuild/scie-pants", python_version="3.9"),
    # public repos
    Repo(name="AlexTereshenkov/cheeseshop-query", python_version="3.9"),
    Repo(name="Ars-Linguistica/mlconjug3", goals=[DefaultGoals.package]),
    Repo(
        name="fucina/treb",
        env={"GIT_COMMIT": "abcdef1234567890"},
        goals=[
            DefaultGoals.lint_check,
            DefaultGoals.test,
            DefaultGoals.package,
        ],
    ),
    Repo(
        name="ghandic/jsf",
        goals=[
            DefaultGoals.test,
            DefaultGoals.package,
        ],
    ),
    Repo(name="komprenilo/liga", python_version="3.9", goals=[DefaultGoals.package]),
    Repo(
        name="lablup/backend.ai",
        python_version="3.11.4",
        setup_commands="mkdir .tmp",
        goals=[
            DefaultGoals.tailor_update_build_files,
            DefaultGoals.lint_check,
            "test :: -tests/agent/docker:: -tests/client/integration:: -tests/common/redis_helper::",
            DefaultGoals.package,
        ],
    ),
    Repo(name="mitodl/ol-infrastructure", goals=[DefaultGoals.package]),
    Repo(
        name="mitodl/ol-django",
        setup_commands="sudo apt-get install pkg-config libxml2-dev libxmlsec1-dev libxmlsec1-openssl",
        goals=[DefaultGoals.package],
    ),
    Repo(
        name="naccdata/flywheel-gear-extensions",
        goals=[DefaultGoals.test, "package :: -directory_pull::"],
    ),
    Repo(name="OpenSaMD/OpenSaMD", python_version="3.9.15"),
    Repo(
        name="StackStorm/st2",
        python_version="3.8",
        checkout_options={"submodules": "recursive"},
        setup_commands=dedent(
            # https://docs.stackstorm.com/development/sources.html
            # TODO: install mongo like this doesn't work, see https://www.mongodb.com/docs/manual/tutorial/install-mongodb-on-ubuntu/
            """
            sudo apt-get install gcc git make screen libffi-dev libssl-dev python3.8-dev libldap2-dev libsasl2-dev
            # sudo apt-get install mongodb mongodb-server
            sudo apt-get install rabbitmq-server
            """
        ),
        goals=[
            DefaultGoals.tailor_update_build_files,
            DefaultGoals.lint_check,
            # TODO: seems like only st2client tests don't depend on mongo
            "test st2client::",
            DefaultGoals.package,
        ],
    ),
]


@dataclass
class PublicReposOutput:
    jobs: Jobs
    inputs: dict[str, Any]
    run_name: str


def public_repos() -> PublicReposOutput:
    """Run tests against public repositories, to validate new versions of Pants.

    See `Repo` for more details.
    """
    inputs, env = workflow_dispatch_inputs(
        [
            WorkflowInput(
                "PANTS_VERSION",
                "string",
                description="Pants version (for example, `2.16.0`, `2.18.0.dev1`)",
            ),
            # extra environment variables to pass when running the version under test,
            # e.g. `PANTS_SOME_SUBSYSTEM_SOME_SETTING=abc`.  NB. we use it in a way that's vulnerable to
            # shell injection (there's no validation that it uses A=1 B=2 syntax, it can easily contain
            # more commands), but this whole workflow is "run untrusted code as a service", so Pants
            # maintainers injecting things is the least of our worries
            WorkflowInput(
                "EXTRA_ENV",
                "string",
                default="",
                description="Extra environment variables (for example: `PANTS_FOO_BAR=1 PANTS_BAZ_QUX=abc`)",
            ),
        ]
    )

    def sanitize_name(name: str) -> str:
        # IDs may only contain alphanumeric characters, '_', and '-'.
        return re.sub("[^A-Za-z0-9_-]+", "_", name)

    def test_job(repo: Repo) -> object:
        def gen_goals(use_default_version: bool) -> Sequence[object]:
            if use_default_version:
                name = "repo-default version (baseline)"
                version = ""
                env_prefix = ""
            else:
                name = version = env["PANTS_VERSION"]
                env_prefix = env["EXTRA_ENV"]

            return [
                {
                    "name": f"Run `{goal}` with {name}",
                    # injecting the input string as just prefices is easier than turning it into
                    # arguments for `env`
                    "run": f"{env_prefix} pants {goal}",
                    # run all the goals, even if there's an earlier failure, because later goals
                    # might still be interesting (e.g. still run `test` even if `lint` fails)
                    "if": "success() || failure()",
                    "env": {"PANTS_VERSION": version},
                }
                for goal in ["version", *repo.goals]
            ]

        job_env: dict[str, str] = {
            **repo.env,
            "PANTS_REMOTE_CACHE_READ": "false",
            "PANTS_REMOTE_CACHE_WRITE": "false",
        }
        return {
            "name": repo.name,
            "runs-on": "ubuntu-latest",
            "env": job_env,
            # we're running untrusted code, so this token shouldn't be able to do anything. We also
            # need to be sure we don't add any secrets to the job
            "permissions": {},
            "steps": [
                *checkout(repository=repo.name, **repo.checkout_options),
                install_python(repo.python_version),
                *([install_go()] if repo.install_go else []),
                *([install_node(repo.node_version)] if repo.node_version else []),
                *([download_apache_thrift()] if repo.install_thrift else []),
                {
                    "name": "Pants on",
                    "run": dedent(
                        # FIXME: save the script somewhere
                        """
                        curl --proto '=https' --tlsv1.2 -fsSL https://static.pantsbuild.org/setup/get-pants.sh | bash -
                        echo "$HOME/bin" | tee -a $GITHUB_PATH
                        """
                    ),
                },
                {
                    # the pants.ci.toml convention is strong, so check for it dynamically rather
                    # than force each repo to mark it specifically
                    "name": "Check for pants.ci.toml",
                    "run": dedent(
                        """
                        if [[ -f pants.ci.toml ]]; then
                            echo "PANTS_CONFIG_FILES=pants.ci.toml" | tee -a $GITHUB_ENV
                        fi
                        """
                    ),
                },
                *(
                    [{"name": "Run set-up", "run": repo.setup_commands}]
                    if repo.setup_commands
                    else []
                ),
                # first run with the repo's base configuration, as a reference point
                *gen_goals(use_default_version=True),
                # FIXME: scie-pants issue
                {
                    "name": "Kill pantsd",
                    "run": "pkill -f pantsd",
                    "if": "success() || failure()",
                },
                # then run with the version under test (simulates an in-place upgrade, locally, too)
                *gen_goals(use_default_version=False),
            ],
        }

    jobs = {sanitize_name(repo.name): test_job(repo) for repo in PUBLIC_REPOS}
    run_name = f"Public repos test: version {env['PANTS_VERSION']} {env['EXTRA_ENV']}"
    return PublicReposOutput(jobs=jobs, inputs=inputs, run_name=run_name)


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

    public_repos_output = public_repos()
    public_repos_yaml = yaml.dump(
        {
            "name": "Public repos tests",
            "run-name": public_repos_output.run_name,
            "on": {"workflow_dispatch": {"inputs": public_repos_output.inputs}},
            "jobs": public_repos_output.jobs,
        },
        Dumper=NoAliasDumper,
    )

    return {
        Path(".github/workflows/audit.yaml"): f"{HEADER}\n\n{audit_yaml}",
        Path(".github/workflows/cache_comparison.yaml"): f"{HEADER}\n\n{cache_comparison_yaml}",
        Path(".github/workflows/test.yaml"): f"{HEADER}\n\n{test_yaml}",
        Path(".github/workflows/release.yaml"): f"{HEADER}\n\n{release_yaml}",
        Path(".github/workflows/public_repos.yaml"): f"{HEADER}\n\n{public_repos_yaml}",
    }


def main() -> None:
    args = create_parser().parse_args()
    generated_yaml = generate()
    if args.check:
        for path, expected in generated_yaml.items():
            actual = path.read_text()
            if actual != expected:
                diff = difflib.unified_diff(
                    actual.splitlines(),
                    expected.splitlines(),
                    fromfile="actual",
                    tofile="expected",
                    lineterm="",
                )
                die(
                    os.linesep.join(
                        (
                            f"Error: Generated path mismatched: {path}",
                            "To re-generate, run: `./pants run src/python/pants_release/generate_github_workflows.py`",
                            "Also note that you might need to merge the latest changes to `main` to this branch.",
                            "Diff:",
                            *diff,
                        )
                    )
                )
    else:
        for path, content in generated_yaml.items():
            path.write_text(content)


if __name__ == "__main__":
    main()
