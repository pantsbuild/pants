# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, Sequence, cast

import toml
import yaml
from common import die

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

LINUX_VERSION = "ubuntu-20.04"
MACOS_VERSION = "macos-11"

DONT_SKIP_RUST = "!contains(env.COMMIT_MESSAGE, '[ci skip-rust]')"
DONT_SKIP_WHEELS = (
    "github.event_name == 'push' || !contains(env.COMMIT_MESSAGE, '[ci skip-build-wheels]')"
)


# NB: This overrides `pants.ci.toml`.
DISABLE_REMOTE_CACHE_ENV = {"PANTS_REMOTE_CACHE_READ": "false", "PANTS_REMOTE_CACHE_WRITE": "false"}
# Works around bad `-arch arm64` flag embedded in Xcode 12.x Python interpreters on
# intel machines. See: https://github.com/giampaolo/psutil/issues/1832
MACOS_ENV = {"ARCHFLAGS": "-arch x86_64"}


IS_PANTS_OWNER = "${{ github.repository_owner == 'pantsbuild' }}"

# ----------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------


def ensure_category_label() -> Sequence[Step]:
    """Check that exactly one category label is present on a pull request."""
    return [
        {
            "if": "github.event_name == 'pull_request'",
            "name": "Ensure category label",
            "uses": "mheap/github-action-required-labels@v1",
            "env": {"GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}"},
            "with": {
                "mode": "exactly",
                "count": 1,
                "labels": "category:new feature, category:user api change, "
                "category:plugin api change, category:performance, category:bugfix, "
                "category:documentation, category:internal",
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
                "run": dedent(
                    """\
                    git config --global safe.directory "$GITHUB_WORKSPACE"
                    """
                ),
            }
        )
    steps.extend(
        [
            # For a push event, the commit we care about is HEAD itself.
            # This CI currently only runs on PRs, so this is future-proofing.
            {
                "name": "Get commit message for branch builds",
                "if": "github.event_name == 'push'",
                "run": dedent(
                    """\
                echo "COMMIT_MESSAGE<<EOF" >> $GITHUB_ENV
                echo "$(git log --format=%B -n 1 HEAD)" >> $GITHUB_ENV
                echo "EOF" >> $GITHUB_ENV
                """
                ),
            },
            # For a pull_request event, the commit we care about is the second parent of the merge
            # commit. This CI currently only runs on PRs, so this is future-proofing.
            {
                "name": "Get commit message for PR builds",
                "if": "github.event_name == 'pull_request'",
                "run": dedent(
                    """\
                echo "COMMIT_MESSAGE<<EOF" >> $GITHUB_ENV
                echo "$(git log --format=%B -n 1 HEAD^2)" >> $GITHUB_ENV
                echo "EOF" >> $GITHUB_ENV
                """
                ),
            },
        ]
    )
    return steps


def setup_toolchain_auth() -> Step:
    return {
        "name": "Setup toolchain auth",
        "if": "github.event_name != 'pull_request'",
        "run": dedent(
            """\
            echo TOOLCHAIN_AUTH_TOKEN="${{ secrets.TOOLCHAIN_AUTH_TOKEN }}" >> $GITHUB_ENV
            """
        ),
    }


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


def rust_caches() -> Sequence[Step]:
    return [
        {
            "name": "Cache Rust toolchain",
            "uses": "actions/cache@v3",
            "with": {
                "path": f"~/.rustup/toolchains/{rust_channel()}-*\n~/.rustup/update-hashes\n~/.rustup/settings.toml\n",
                "key": "${{ runner.os }}-rustup-${{ hashFiles('rust-toolchain') }}-v1",
            },
        },
        {
            "name": "Cache Cargo",
            "uses": "actions/cache@v3",
            "with": {
                "path": "~/.cargo/registry\n~/.cargo/git\n",
                "key": "${{ runner.os }}-cargo-${{ hashFiles('rust-toolchain') }}-${{ hashFiles('src/rust/engine/Cargo.*') }}-v1\n",
                "restore-keys": "${{ runner.os }}-cargo-${{ hashFiles('rust-toolchain') }}-\n",
            },
        },
    ]


def install_jdk() -> Step:
    return {
        "name": "Install AdoptJDK",
        "uses": "actions/setup-java@v2",
        "with": {
            "distribution": "adopt",
            "java-version": "11",
        },
    }


def install_go() -> Step:
    return {
        "name": "Install Go",
        "uses": "actions/setup-go@v2",
        "with": {"go-version": "1.17.1"},
    }


def bootstrap_caches() -> Sequence[Step]:
    return [
        *rust_caches(),
        # NB: This caching is only intended for the bootstrap jobs to avoid them needing to
        # re-compile when possible. Compare to the upload-artifact and download-artifact actions,
        # which are how the bootstrap jobs share the compiled binaries with the other jobs like
        # `lint` and `test`.
        {
            "name": "Get native engine hash",
            "id": "get-engine-hash",
            "run": 'echo "::set-output name=hash::$(./build-support/bin/rust/print_engine_hash.sh)"\n',
            "shell": "bash",
        },
        {
            "name": "Cache native engine",
            "uses": "actions/cache@v3",
            "with": {
                "path": "\n".join(NATIVE_FILES),
                "key": "${{ runner.os }}-engine-${{ steps.get-engine-hash.outputs.hash }}-v1\n",
            },
        },
    ]


def native_binaries_upload() -> Step:
    return {
        "name": "Upload native binaries",
        "uses": "actions/upload-artifact@v2",
        "with": {
            "name": "native_binaries.${{ matrix.python-version }}.${{ runner.os }}",
            "path": "\n".join(NATIVE_FILES),
        },
    }


def native_binaries_download() -> Step:
    return {
        "name": "Download native binaries",
        "uses": "actions/download-artifact@v2",
        "with": {"name": "native_binaries.${{ matrix.python-version }}.${{ runner.os }}"},
    }


def setup_primary_python() -> Sequence[Step]:
    return [
        {
            "name": "Set up Python ${{ matrix.python-version }}",
            "uses": "actions/setup-python@v2",
            "with": {"python-version": "${{ matrix.python-version }}"},
        },
        {
            "name": "Tell Pants to use Python ${{ matrix.python-version }}",
            "run": dedent(
                """\
                echo "PY=python${{ matrix.python-version }}" >> $GITHUB_ENV
                echo "PANTS_PYTHON_INTERPRETER_CONSTRAINTS=['==${{ matrix.python-version }}.*']" >> $GITHUB_ENV
                """
            ),
        },
    ]


def expose_all_pythons() -> Step:
    return {
        "name": "Expose Pythons",
        "uses": "pantsbuild/actions/expose-pythons@627a8ce25d972afa03da1641be9261bbbe0e3ffe",
    }


def upload_log_artifacts(name: str) -> Step:
    return {
        "name": "Upload pants.log",
        "uses": "actions/upload-artifact@v2",
        "if": "always()",
        "with": {"name": f"pants-log-{name}", "path": ".pants.d/pants.log"},
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


def test_workflow_jobs(python_versions: list[str], *, cron: bool) -> Jobs:
    jobs = {
        "check_labels": {
            "name": "Ensure PR has a category label",
            "runs-on": LINUX_VERSION,
            "if": IS_PANTS_OWNER,
            "steps": ensure_category_label(),
        },
        "bootstrap_pants_linux": {
            "name": "Bootstrap Pants, test+lint Rust (Linux)",
            "runs-on": LINUX_VERSION,
            "needs": "check_labels",
            "strategy": {"matrix": {"python-version": python_versions}},
            "env": DISABLE_REMOTE_CACHE_ENV,
            "timeout-minutes": 40,
            "if": IS_PANTS_OWNER,
            "steps": [
                *checkout(),
                *setup_primary_python(),
                *bootstrap_caches(),
                setup_toolchain_auth(),
                {"name": "Bootstrap Pants", "run": "./pants --version\n"},
                {
                    "name": "Validate CI config",
                    "run": dedent(
                        """\
                        ./pants run build-support/bin/generate_github_workflows.py -- --check
                        """
                    ),
                },
                {
                    "name": "Run smoke tests",
                    "run": dedent(
                        """\
                        ./pants list ::
                        ./pants roots
                        ./pants help goals
                        ./pants help targets
                        ./pants help subsystems
                        """
                    ),
                },
                upload_log_artifacts(name="bootstrap-linux"),
                native_binaries_upload(),
                {
                    "name": "Test and Lint Rust",
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
        "test_python_linux": {
            "name": "Test Python (Linux)",
            "runs-on": LINUX_VERSION,
            "needs": "bootstrap_pants_linux",
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
                native_binaries_download(),
                setup_toolchain_auth(),
                {"name": "Run Python tests", "run": "./pants test ::\n"},
                upload_log_artifacts(name="python-test-linux"),
            ],
        },
        "lint_python": {
            "name": "Lint Python and Shell",
            "runs-on": LINUX_VERSION,
            "needs": "bootstrap_pants_linux",
            "strategy": {"matrix": {"python-version": python_versions}},
            "timeout-minutes": 30,
            "if": IS_PANTS_OWNER,
            "steps": [
                *checkout(),
                *setup_primary_python(),
                native_binaries_download(),
                setup_toolchain_auth(),
                {
                    "name": "Lint",
                    "run": (
                        "./pants update-build-files --check\n"
                        # Note: we use `**` rather than `::` because regex-lint.
                        "./pants lint check '**'\n"
                    ),
                },
                upload_log_artifacts(name="lint"),
            ],
        },
        "bootstrap_pants_macos": {
            "name": "Bootstrap Pants, test Rust (macOS)",
            "runs-on": MACOS_VERSION,
            "needs": "check_labels",
            "strategy": {"matrix": {"python-version": python_versions}},
            "env": DISABLE_REMOTE_CACHE_ENV,
            "timeout-minutes": 40,
            "if": IS_PANTS_OWNER,
            "steps": [
                *ensure_category_label(),
                *checkout(),
                *setup_primary_python(),
                *bootstrap_caches(),
                setup_toolchain_auth(),
                {"name": "Bootstrap Pants", "run": "./pants --version\n"},
                native_binaries_upload(),
                {
                    "name": "Test Rust",
                    # We pass --tests to skip doc tests because our generated protos contain
                    # invalid doc tests in their comments. We do not pass --all as BRFS tests don't
                    # pass on GHA MacOS containers.
                    "run": "./cargo test --tests -- --nocapture",
                    "if": DONT_SKIP_RUST,
                    "env": {"TMPDIR": "${{ runner.temp }}"},
                },
            ],
        },
        "test_python_macos": {
            "name": "Test Python (macOS)",
            "runs-on": MACOS_VERSION,
            "needs": "bootstrap_pants_macos",
            "strategy": {"matrix": {"python-version": python_versions}},
            "env": MACOS_ENV,
            "timeout-minutes": 60,
            "if": IS_PANTS_OWNER,
            "steps": [
                *checkout(),
                install_jdk(),
                *setup_primary_python(),
                expose_all_pythons(),
                native_binaries_download(),
                setup_toolchain_auth(),
                {
                    "name": "Run Python tests",
                    "run": (
                        "./pants --tag=+platform_specific_behavior test :: "
                        "-- -m platform_specific_behavior\n"
                    ),
                },
                upload_log_artifacts(name="python-test-macos"),
            ],
        },
    }
    if not cron:

        def build_steps(*, is_macos: bool) -> list[Step]:
            env = {"PANTS_CONFIG_FILES": "+['pants.ci.toml']", **(MACOS_ENV if is_macos else {})}
            return [
                {
                    "name": "Build wheels",
                    "run": dedent(
                        # We use MODE=debug on PR builds to speed things up, given that those are
                        # only smoke tests of our release process.
                        # Note that the build-local-pex run is just for smoke-testing that pex
                        # builds work, and it must come *before* the build-wheels runs, since
                        # it cleans out `dist/deploy`, which the build-wheels runs populate for
                        # later attention by deploy_to_s3.py.
                        """\
                        [[ "${GITHUB_EVENT_NAME}" == "pull_request" ]] && export MODE=debug
                        ./build-support/bin/release.sh build-local-pex
                        ./build-support/bin/release.sh build-wheels
                        USE_PY38=true ./build-support/bin/release.sh build-wheels
                        USE_PY39=true ./build-support/bin/release.sh build-wheels
                        ./build-support/bin/release.sh build-fs-util
                        """
                    ),
                    "if": DONT_SKIP_WHEELS,
                    "env": env,
                },
                {
                    "name": "Build fs_util",
                    "run": "./build-support/bin/release.sh build-fs-util",
                    # We only build fs_util on branch builds, given that Pants compilation already
                    # checks the code compiles and the release process is simple and low-stakes.
                    "if": "github.event_name == 'push'",
                    "env": env,
                },
            ]

        build_wheels_common = {
            "needs": "check_labels",
            "env": DISABLE_REMOTE_CACHE_ENV,
            "if": IS_PANTS_OWNER,
        }
        deploy_to_s3_step = {
            "name": "Deploy to S3",
            "run": "./build-support/bin/deploy_to_s3.py",
            "if": "github.event_name == 'push'",
            "env": {
                "AWS_SECRET_ACCESS_KEY": "${{ secrets.AWS_SECRET_ACCESS_KEY }}",
                "AWS_ACCESS_KEY_ID": "${{ secrets.AWS_ACCESS_KEY_ID }}",
            },
        }
        jobs.update(
            {
                "build_wheels_linux_x86_64": {
                    "name": "Build wheels and fs_util (Linux x86/64)",
                    "runs-on": LINUX_VERSION,
                    "container": "quay.io/pypa/manylinux2014_x86_64:latest",
                    "timeout-minutes": 65,
                    **build_wheels_common,
                    "steps": [
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
                        setup_toolchain_auth(),
                        *build_steps(is_macos=False),
                        upload_log_artifacts(name="wheels-linux"),
                        deploy_to_s3_step,
                    ],
                },
                "build_wheels_macos_x86_64": {
                    "name": "Build wheels and fs_util (macOS x86/64)",
                    "runs-on": MACOS_VERSION,
                    "timeout-minutes": 80,
                    **build_wheels_common,
                    "steps": [
                        *checkout(),
                        setup_toolchain_auth(),
                        expose_all_pythons(),
                        # NB: We only cache Rust, but not `native_engine.so` and the Pants
                        # virtualenv. This is because we must build both these things with Python
                        # multiple Python versions, whereas that caching assumes only one primary
                        # Python version (marked via matrix.strategy).
                        *rust_caches(),
                        *build_steps(is_macos=True),
                        upload_log_artifacts(name="wheels-macos"),
                        deploy_to_s3_step,
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
    env = {
        wi.name: ("${{ github.event.inputs." + wi.name.lower() + " }}") for wi in workflow_inputs
    }
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
                setup_toolchain_auth(),
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


def generate() -> dict[Path, str]:
    """Generate all YAML configs with repo-relative paths."""

    test_workflow_name = "Pull Request CI"
    test_yaml = yaml.dump(
        {
            "name": test_workflow_name,
            "on": {"pull_request": {}, "push": {"branches-ignore": ["dependabot/**"]}},
            "jobs": test_workflow_jobs([PYTHON37_VERSION], cron=False),
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
                            "uses": "styfle/cancel-workflow-action@0.8.0",
                            "with": {
                                "workflow_id": "${{ github.event.workflow.id }}",
                                "access_token": "${{ github.token }}",
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

    return {
        Path(".github/workflows/audit.yaml"): f"{HEADER}\n\n{audit_yaml}",
        Path(".github/workflows/cache_comparison.yaml"): f"{HEADER}\n\n{cache_comparison_yaml}",
        Path(".github/workflows/cancel.yaml"): f"{HEADER}\n\n{cancel_yaml}",
        Path(".github/workflows/test.yaml"): f"{HEADER}\n\n{test_yaml}",
        Path(".github/workflows/test-cron.yaml"): f"{HEADER}\n\n{test_cron_yaml}",
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
