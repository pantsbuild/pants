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
    MACOS10_15_X86_64 = "macOS10-15-x86_64"
    MACOS11_X86_64 = "macOS11-x86_64"
    MACOS11_ARM64 = "macOS11-ARM64"


GITHUB_HOSTED = {Platform.LINUX_X86_64, Platform.MACOS11_X86_64}
SELF_HOSTED = {Platform.MACOS10_15_X86_64, Platform.MACOS11_ARM64}


def gha_expr(expr: str) -> str:
    """Properly quote GitHub Actions expressions.

    Because we use f-strings often, but not always, in this script, it is very easy to get the
    quoting of the double curly braces wrong, especially when changing a non-f-string to an f-string
    or vice versa. So instead we universally delegate to this function.
    """
    # Here we use simple string concat instead of getting tangled up with escaping in f-strings.
    return "${{ " + expr + " }}"


def hashFiles(path: str) -> str:
    """Generate a properly quoted hashFiles call for the given path."""
    return gha_expr(f"hashFiles('{path}')")


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------


NATIVE_FILES = [
    ".pants",
    "src/python/pants/engine/internals/native_engine.so",
    "src/python/pants/engine/internals/native_engine.so.metadata",
]

# We don't specify patch versions so that we get the latest, which comes pre-installed:
#  https://github.com/actions/setup-python#available-versions-of-python
PYTHON37_VERSION = "3.7"
PYTHON38_VERSION = "3.8"
PYTHON39_VERSION = "3.9"
ALL_PYTHON_VERSIONS = [PYTHON37_VERSION, PYTHON38_VERSION, PYTHON39_VERSION]

DONT_SKIP_RUST = "needs.classify_changes.outputs.rust == 'true'"
DONT_SKIP_WHEELS = "github.event_name == 'push' || needs.classify_changes.outputs.release == 'true'"
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
                    "id": "files",
                    "name": "Get changed files",
                    "uses": "tj-actions/changed-files@v32",
                    "with": {"separator": "|"},
                },
                {
                    "id": "classify",
                    "name": "Classify changed files",
                    "run": dedent(
                        f"""\
                        affected=$(python build-support/bin/classify_changed_files.py "{gha_expr("steps.files.outputs.all_modified_files")}")
                        echo "Affected:"
                        if [[ "${{affected}}" == "docs" ]]; then
                          echo "docs_only=true" >> $GITHUB_OUTPUT
                          echo "docs_only"
                        fi
                        for i in ${{affected}}; do
                          echo "${{i}}=true" >> $GITHUB_OUTPUT
                          echo "${{i}}"
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
            "uses": "mheap/github-action-required-labels@v2.1.0",
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


def checkout(*, containerized: bool = False) -> Sequence[Step]:
    """Get prior commits and the commit message."""
    steps = [
        # See https://github.community/t/accessing-commit-message-in-pull-request-event/17158/8
        # for details on how we get the commit message here.
        # We need to fetch a few commits back, to be able to access HEAD^2 in the PR case.
        {
            "name": "Check out code",
            "uses": "actions/checkout@v3",
            "with": {"fetch-depth": 10},
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
            echo "PATH=${PATH}:${HOME}/.cargo/bin" >> $GITHUB_ENV
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
        "with": {"go-version": "1.17.1"},
    }


def deploy_to_s3(when: str = "github.event_name == 'push'", scope: str | None = None) -> Step:
    run = "./build-support/bin/deploy_to_s3.py"
    if scope:
        run = f"{run} --scope {scope}"
    return {
        "name": "Deploy to S3",
        "run": run,
        "if": when,
        "env": {
            "AWS_SECRET_ACCESS_KEY": f"{gha_expr('secrets.AWS_SECRET_ACCESS_KEY')}",
            "AWS_ACCESS_KEY_ID": f"{gha_expr('secrets.AWS_ACCESS_KEY_ID')}",
        },
    }


def setup_primary_python(install_python: bool = True) -> Sequence[Step]:
    ret = []
    if install_python:
        ret.append(
            {
                "name": f"Set up Python {gha_expr('matrix.python-version')}",
                "uses": "actions/setup-python@v4",
                "with": {"python-version": f"{gha_expr('matrix.python-version')}"},
            }
        )
    ret.append(
        {
            "name": f"Tell Pants to use Python {gha_expr('matrix.python-version')}",
            "run": dedent(
                f"""\
                echo "PY=python{gha_expr('matrix.python-version')}" >> $GITHUB_ENV
                echo "PANTS_PYTHON_INTERPRETER_CONSTRAINTS=['=={gha_expr('matrix.python-version')}.*']" >> $GITHUB_ENV
                """
            ),
        }
    )
    return ret


def expose_all_pythons() -> Step:
    return {
        "name": "Expose Pythons",
        "uses": "pantsbuild/actions/expose-pythons@627a8ce25d972afa03da1641be9261bbbe0e3ffe",
    }


def download_apache_thrift() -> Step:
    return {
        "name": "Download Apache `thrift` binary (Linux)",
        "if": "runner.os == 'Linux'",
        "run": dedent(
            """\
            mkdir -p "$HOME/.thrift"
            curl --fail -L https://binaries.pantsbuild.org/bin/thrift/linux/x86_64/0.15.0/thrift -o "$HOME/.thrift/thrift"
            chmod +x "$HOME/.thrift/thrift"
            echo "PATH=${PATH}:${HOME}/.thrift" >> $GITHUB_ENV
            """
        ),
    }


class Helper:
    def __init__(self, platform: Platform):
        self.platform = platform

    def platform_name(self) -> str:
        return str(self.platform.value)

    def runs_on(self) -> list[str]:
        if self.platform == Platform.MACOS11_X86_64:
            return ["macos-11"]
        if self.platform == Platform.MACOS11_ARM64:
            return ["macOS-11-ARM64"]
        if self.platform == Platform.MACOS10_15_X86_64:
            return ["macOS-10.15-X64"]
        if self.platform == Platform.LINUX_X86_64:
            return ["ubuntu-20.04"]
        raise ValueError(f"Unsupported platform: {self.platform_name()}")

    def platform_env(self):
        ret = {}
        if self.platform in {Platform.MACOS10_15_X86_64, Platform.MACOS11_X86_64}:
            # Works around bad `-arch arm64` flag embedded in Xcode 12.x Python interpreters on
            # intel machines. See: https://github.com/giampaolo/psutil/issues/1832
            ret["ARCHFLAGS"] = "-arch x86_64"
        if self.platform == Platform.MACOS11_ARM64:
            ret["ARCHFLAGS"] = "-arch arm64"
        return ret

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

    def native_binaries_download(self) -> Step:
        return {
            "name": "Download native binaries",
            "uses": "actions/download-artifact@v3",
            "with": {
                "name": f"native_binaries.{gha_expr('matrix.python-version')}.{self.platform_name()}",
            },
        }

    def rust_caches(self) -> Sequence[Step]:
        return [
            {
                "name": "Cache Rust toolchain",
                "uses": "actions/cache@v3",
                "with": {
                    "path": f"~/.rustup/toolchains/{rust_channel()}-*\n~/.rustup/update-hashes\n~/.rustup/settings.toml\n",
                    "key": f"{self.platform_name()}-rustup-{hashFiles('rust-toolchain')}-v2",
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

    def bootstrap_pants(self, *, install_python: bool) -> Sequence[Step]:
        return [
            *checkout(),
            *setup_primary_python(install_python=install_python),
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

    def build_wheels(self, python_versions: list[str]) -> list[Step]:
        cmd = dedent(
            # We use MODE=debug on PR builds to speed things up, given that those are
            # only smoke tests of our release process.
            # Note that the build-local-pex run is just for smoke-testing that pex
            # builds work, and it must come *before* the build-wheels runs, since
            # it cleans out `dist/deploy`, which the build-wheels runs populate for
            # later attention by deploy_to_s3.py.
            """\
            [[ "${GITHUB_EVENT_NAME}" == "pull_request" ]] && export MODE=debug
            USE_PY39=true ./build-support/bin/release.sh build-local-pex
            """
        )

        def build_wheels_for(env_var: str) -> str:
            env_setting = f"{env_var}=true " if env_var else ""
            return f"\n{env_setting}./build-support/bin/release.sh build-wheels"

        if PYTHON37_VERSION in python_versions:
            cmd += build_wheels_for("")
        if PYTHON38_VERSION in python_versions:
            cmd += build_wheels_for("USE_PY38")
        if PYTHON39_VERSION in python_versions:
            cmd += build_wheels_for("USE_PY39")

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


def linux_x86_64_test_jobs(python_versions: list[str]) -> Jobs:
    helper = Helper(Platform.LINUX_X86_64)

    def test_python_linux(shard: str) -> dict[str, Any]:
        return {
            "name": f"Test Python ({helper.platform_name()}) Shard {shard}",
            "runs-on": helper.runs_on(),
            "needs": "bootstrap_pants_linux_x86_64",
            "strategy": {"matrix": {"python-version": python_versions}},
            "timeout-minutes": 90,
            "if": IS_PANTS_OWNER,
            "steps": [
                *checkout(),
                install_jdk(),
                install_go(),
                download_apache_thrift(),
                *setup_primary_python(),
                expose_all_pythons(),
                helper.native_binaries_download(),
                {
                    "name": f"Run Python test shard {shard}",
                    "run": f"./pants test --shard={shard} ::\n",
                },
                helper.upload_log_artifacts(name=f"python-test-{shard}"),
            ],
        }

    jobs = {
        "bootstrap_pants_linux_x86_64": {
            "name": f"Bootstrap Pants, test and lint Rust ({helper.platform_name()})",
            "runs-on": helper.runs_on(),
            "strategy": {"matrix": {"python-version": python_versions}},
            "env": DISABLE_REMOTE_CACHE_ENV,
            "timeout-minutes": 40,
            "if": IS_PANTS_OWNER,
            "steps": [
                *helper.bootstrap_pants(install_python=True),
                {
                    "name": "Validate CI config",
                    "run": dedent(
                        """\
                        ./pants run build-support/bin/generate_github_workflows.py -- --check
                        """
                    ),
                },
                {
                    "name": "Test and lint Rust",
                    # We pass --tests to skip doc tests because our generated protos contain
                    # invalid doc tests in their comments.
                    "run": dedent(
                        """\
                        sudo apt-get install -y pkg-config fuse libfuse-dev
                        ./build-support/bin/check_rust_pre_commit.sh
                        ./cargo test --all --tests -- --nocapture
                        ./cargo check --benches
                        """
                    ),
                    "if": DONT_SKIP_RUST,
                },
            ],
        },
        "test_python_linux_x86_64_0": test_python_linux("0/3"),
        "test_python_linux_x86_64_1": test_python_linux("1/3"),
        "test_python_linux_x86_64_2": test_python_linux("2/3"),
    }
    return jobs


def macos11_x86_64_test_jobs(python_versions: list[str]) -> Jobs:
    helper = Helper(Platform.MACOS11_X86_64)
    jobs = {
        "bootstrap_pants_macos11_x86_64": {
            "name": f"Bootstrap Pants, test Rust ({helper.platform_name()})",
            "runs-on": helper.runs_on(),
            "strategy": {"matrix": {"python-version": python_versions}},
            "env": DISABLE_REMOTE_CACHE_ENV,
            "timeout-minutes": 60,
            "if": IS_PANTS_OWNER,
            "steps": [
                *helper.bootstrap_pants(install_python=True),
                {
                    "name": "Test Rust",
                    # We pass --tests to skip doc tests because our generated protos contain
                    # invalid doc tests in their comments. We do not pass --all as BRFS tests don't
                    # pass on GHA MacOS containers.
                    "run": helper.wrap_cmd("./cargo test --tests -- --nocapture"),
                    "env": {"TMPDIR": f"{gha_expr('runner.temp')}"},
                    "if": DONT_SKIP_RUST,
                },
            ],
        },
        "test_python_macos11_x86_64": {
            "name": f"Test Python ({helper.platform_name()})",
            "runs-on": helper.runs_on(),
            "needs": "bootstrap_pants_macos11_x86_64",
            "strategy": {"matrix": {"python-version": python_versions}},
            "env": helper.platform_env(),
            "timeout-minutes": 60,
            "if": IS_PANTS_OWNER,
            "steps": [
                *checkout(),
                install_jdk(),
                *setup_primary_python(),
                expose_all_pythons(),
                helper.native_binaries_download(),
                {
                    "name": "Run Python tests",
                    "run": softwrap(
                        """
                        ./pants --tag=+platform_specific_behavior test ::
                        -- -m platform_specific_behavior
                        """
                    ),
                },
                helper.upload_log_artifacts(name="python-test"),
            ],
        },
    }
    return jobs


def build_wheels_job(platform: Platform, python_versions: list[str]) -> Jobs:
    helper = Helper(platform)
    if platform == Platform.LINUX_X86_64:
        # For manylinux compatibility, we build wheels in a container rather than directly
        # on the Ubuntu runner. As a result, we have custom steps here to check out
        # the code, install rustup and expose Pythons.
        # TODO: Apply rust caching here.
        container = "quay.io/pypa/manylinux2014_x86_64:latest"
        initial_steps = [
            *checkout(containerized=True),
            install_rustup(),
            {
                "name": "Expose Pythons",
                "run": (
                    'echo "PATH=${PATH}:'
                    "/opt/python/cp37-cp37m/bin:"
                    "/opt/python/cp38-cp38/bin:"
                    '/opt/python/cp39-cp39/bin" >> $GITHUB_ENV'
                ),
            },
        ]
    else:
        container = None
        initial_steps = [
            *checkout(),
            # Self-hosted runners already have all relevant pythons exposed on their PATH, so we
            # only run expose_all_pythons() on the GitHub-hosted platforms.
            *([expose_all_pythons()] if platform in GITHUB_HOSTED else []),
            # NB: We only cache Rust, but not `native_engine.so` and the Pants
            # virtualenv. This is because we must build both these things with
            # multiple Python versions, whereas that caching assumes only one primary
            # Python version (marked via matrix.strategy).
            *helper.rust_caches(),
        ]
    return {
        f"build_wheels_{str(platform.value).lower().replace('-', '_')}": {
            "if": f"({IS_PANTS_OWNER}) && ({DONT_SKIP_WHEELS})",
            "name": f"Build wheels ({str(platform.value)})",
            "runs-on": helper.runs_on(),
            **({"container": container} if container else {}),
            "timeout-minutes": 90,
            "env": DISABLE_REMOTE_CACHE_ENV,
            "steps": initial_steps
            + [
                *helper.build_wheels(python_versions),
                helper.upload_log_artifacts(name="wheels"),
                deploy_to_s3(),
            ],
        },
    }


def build_wheels_jobs() -> Jobs:
    return {
        **build_wheels_job(Platform.LINUX_X86_64, ALL_PYTHON_VERSIONS),
        **build_wheels_job(Platform.MACOS10_15_X86_64, ALL_PYTHON_VERSIONS),
        **build_wheels_job(Platform.MACOS11_ARM64, [PYTHON39_VERSION]),
    }


def test_workflow_jobs(python_versions: list[str], *, cron: bool) -> Jobs:
    linux_x86_64_helper = Helper(Platform.LINUX_X86_64)
    jobs: dict[str, Any] = {
        "check_labels": {
            "name": "Ensure PR has a category label",
            "runs-on": linux_x86_64_helper.runs_on(),
            "if": IS_PANTS_OWNER,
            "steps": ensure_category_label(),
        },
    }
    jobs.update(**linux_x86_64_test_jobs(python_versions))
    jobs.update(**macos11_x86_64_test_jobs(python_versions))
    if not cron:
        jobs.update(**build_wheels_jobs())
    jobs.update(
        {
            "lint_python": {
                "name": "Lint Python and Shell",
                "runs-on": linux_x86_64_helper.runs_on(),
                "needs": "bootstrap_pants_linux_x86_64",
                "strategy": {"matrix": {"python-version": python_versions}},
                "timeout-minutes": 30,
                "if": IS_PANTS_OWNER,
                "steps": [
                    *checkout(),
                    *setup_primary_python(),
                    linux_x86_64_helper.native_binaries_download(),
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

    jobs = {
        "cache_comparison": {
            "runs-on": "ubuntu-latest",
            "timeout-minutes": 90,
            # TODO: This job doesn't actually need to run as a matrix, but `setup_primary_python`
            # assumes that jobs are.
            "strategy": {"matrix": {"python-version": [PYTHON37_VERSION]}},
            "steps": [
                *checkout(),
                *setup_primary_python(),
                expose_all_pythons(),
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
    inputs, env = workflow_dispatch_inputs([WorkflowInput("TAG", "string")])

    jobs = {
        "publish-tag-to-commit-mapping": {
            "runs-on": "ubuntu-latest",
            "if": IS_PANTS_OWNER,
            "steps": [
                {
                    "name": "Determine Release Tag",
                    "id": "determine-tag",
                    "env": env,
                    "run": dedent(
                        """\
                        if [[ -n "$TAG" ]]; then
                            tag="$TAG"
                        else
                            tag="${GITHUB_REF#refs/tags/}"
                        fi
                        if [[ "${tag}" =~ ^release_.+$ ]]; then
                            echo "release-tag=${tag}" >> $GITHUB_OUTPUT
                        else
                            echo "::error::Release tag '${tag}' must match 'release_.+'."
                            exit 1
                        fi
                        """
                    ),
                },
                {
                    "name": "Checkout Pants at Release Tag",
                    "uses": "actions/checkout@v3",
                    "with": {"ref": f"{gha_expr('steps.determine-tag.outputs.release-tag')}"},
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
                        tag="{gha_expr("steps.determine-tag.outputs.release-tag")}"
                        commit="$(git rev-parse ${{tag}}^{{commit}})"

                        echo "Recording tag ${{tag}} is of commit ${{commit}}"
                        mkdir -p dist/deploy/tags/pantsbuild.pants
                        echo "${{commit}}" > "dist/deploy/tags/pantsbuild.pants/${{tag}}"
                        """
                    ),
                },
                deploy_to_s3(
                    when="github.event_name == 'push' || github.event_name == 'workflow_dispatch'",
                    scope="tags/pantsbuild.pants",
                ),
            ],
        }
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

    pr_jobs = test_workflow_jobs([PYTHON37_VERSION], cron=False)
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
            "on": {"pull_request": {}, "push": {"branches-ignore": ["dependabot/**"]}},
            "jobs": pr_jobs,
            "env": global_env(),
        },
        Dumper=NoAliasDumper,
    )

    test_cron_yaml = yaml.dump(
        {
            "name": "Daily Extended Python Testing",
            # 08:45 UTC / 12:45AM PST, 1:45AM PDT: arbitrary time after hours.
            "on": {"schedule": [{"cron": "45 8 * * *"}]},
            "jobs": test_workflow_jobs([PYTHON38_VERSION, PYTHON39_VERSION], cron=True),
            "env": global_env(),
        },
        Dumper=NoAliasDumper,
    )

    cancel_yaml = yaml.dump(
        {
            # Note that this job runs in the context of the default branch, so its token
            # has permission to cancel workflows (i.e., it is not the PR's read-only token).
            "name": "Cancel",
            "on": {
                "workflow_run": {
                    "workflows": [test_workflow_name],
                    "types": ["requested"],
                    # Never cancel branch builds for `main` and release branches.
                    "branches-ignore": ["main", "2.*.x"],
                }
            },
            "jobs": {
                "cancel": {
                    "runs-on": "ubuntu-latest",
                    "if": IS_PANTS_OWNER,
                    "steps": [
                        {
                            "uses": "styfle/cancel-workflow-action@0.9.1",
                            "with": {
                                "workflow_id": f"{gha_expr('github.event.workflow.id')}",
                                "access_token": f"{gha_expr('github.token')}",
                            },
                        }
                    ],
                }
            },
        }
    )

    audit_yaml = yaml.dump(
        {
            "name": "Cargo Audit",
            # 08:11 UTC / 12:11AM PST, 1:11AM PDT: arbitrary time after hours.
            "on": {"schedule": [{"cron": "11 8 * * *"}]},
            "jobs": {
                "audit": {
                    "runs-on": "ubuntu-latest",
                    "if": IS_PANTS_OWNER,
                    "steps": [
                        *checkout(),
                        {
                            "name": "Cargo audit (for security vulnerabilities)",
                            "run": "./cargo install --version 0.16.0 cargo-audit\n./cargo audit\n",
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
            "name": "Record Release Commit",
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
        Path(".github/workflows/cancel.yaml"): f"{HEADER}\n\n{cancel_yaml}",
        Path(".github/workflows/test.yaml"): f"{HEADER}\n\n{test_yaml}",
        Path(".github/workflows/test-cron.yaml"): f"{HEADER}\n\n{test_cron_yaml}",
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
