# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, Sequence

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


def checkout() -> Sequence[Step]:
    return [
        # See https://github.community/t/accessing-commit-message-in-pull-request-event/17158/8
        # for details on how we get the commit message here.
        # We need to fetch a few commits back, to be able to access HEAD^2 in the PR case.
        {
            "name": "Check out code",
            "uses": "actions/checkout@v2",
            "with": {"fetch-depth": 10},
        },
        # For a push event, the commit we care about is HEAD itself.
        # This CI currently only runs on PRs, so this is future-proofing.
        {
            "name": "Get commit message for branch builds",
            "if": "github.event_name == 'push'",
            "run": 'echo "COMMIT_MESSAGE<<EOF" >> $GITHUB_ENV\necho "$(git log --format=%B -n 1 HEAD)" >> $GITHUB_ENV\necho "EOF" >> $GITHUB_ENV\n',
        },
        # For a pull_request event, the commit we care about is the second parent of the merge commit.
        # This CI currently only runs on PRs, so this is future-proofing.
        {
            "name": "Get commit message for PR builds",
            "if": "github.event_name == 'pull_request'",
            "run": 'echo "COMMIT_MESSAGE<<EOF" >> $GITHUB_ENV\necho "$(git log --format=%B -n 1 HEAD^2)" >> $GITHUB_ENV\necho "EOF" >> $GITHUB_ENV\n',
        },
    ]


def pants_virtualenv_cache() -> Sequence[Step]:
    return [
        {
            "name": "Cache Pants Virtualenv",
            "uses": "actions/cache@v2",
            "with": {
                "path": "~/.cache/pants/pants_dev_deps\n",
                "key": "${{ runner.os }}-pants-venv-${{ matrix.python-version }}-${{ hashFiles('pants/3rdparty/python/**', 'pants.toml') }}\n",
            },
        }
    ]


def pants_config_files() -> Sequence[Step]:
    return [
        {
            "name": "Set pants config files",
            "run": 'echo \'PANTS_CONFIG_FILES=+["${{ github.workspace }}/pants.ci.toml", "${{ github.workspace }}/pants.remote-cache.toml"]\' >> ${GITHUB_ENV}\n',
        },
    ]


def bootstrap_caches() -> Sequence[Step]:
    return [
        {
            "name": "Cache Rust toolchain",
            "uses": "actions/cache@v2",
            "with": {
                "path": "~/.rustup/toolchains/${{ env.rust_version }}-*\n~/.rustup/update-hashes\n~/.rustup/settings.toml\n",
                "key": "${{ runner.os }}-rustup-${{ hashFiles('rust-toolchain') }}",
            },
        },
        {
            "name": "Cache Cargo",
            "uses": "actions/cache@v2",
            "with": {
                "path": "~/.cargo/registry\n~/.cargo/git\n",
                "key": "${{ runner.os }}-cargo-${{ hashFiles('rust-toolchain') }}-${{ hashFiles('src/rust/engine/Cargo.*') }}\n",
                "restore-keys": "${{ runner.os }}-cargo-${{ hashFiles('rust-toolchain') }}-\n",
            },
        },
        *pants_virtualenv_cache(),
        {
            "name": "Get Engine Hash",
            "id": "get-engine-hash",
            "run": 'echo "::set-output name=hash::$(./build-support/bin/rust/print_engine_hash.sh)"\n',
            "shell": "bash",
        },
        {
            "name": "Cache Native Engine",
            "uses": "actions/cache@v2",
            "with": {
                "path": "src/python/pants/engine/internals/native_engine.so\nsrc/python/pants/engine/internals/native_engine.so.metadata\n",
                "key": "${{ runner.os }}-engine-${{ steps.get-engine-hash.outputs.hash }}\n",
            },
        },
    ]


def native_engine_so_upload() -> Sequence[Step]:
    return [
        {
            "name": "Upload native_engine.so",
            "uses": "actions/upload-artifact@v2",
            "with": {
                "name": "native_engine.so.${{ matrix.python-version }}.${{ runner.os }}",
                "path": "src/python/pants/engine/internals/native_engine.so\nsrc/python/pants/engine/internals/native_engine.so.metadata\n",
            },
        },
    ]


def native_engine_so_download() -> Sequence[Step]:
    return [
        {
            "name": "Download native_engine.so",
            "uses": "actions/download-artifact@v2",
            "with": {
                "name": "native_engine.so.${{ matrix.python-version }}.${{ runner.os }}",
                "path": "src/python/pants/engine/internals/",
            },
        },
    ]


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
    test_yaml = yaml.dump(
        {
            "name": "Pull Request CI",
            "on": "pull_request",
            "jobs": {
                "bootstrap_pants_linux": {
                    "name": "Bootstrap Pants, test+lint Rust (Linux)",
                    "runs-on": "ubuntu-20.04",
                    "strategy": {"matrix": {"python-version": ["3.7.10"]}},
                    "env": {"rust_version": "1.49.0"},
                    "steps": [
                        *checkout(),
                        {
                            "name": "Set up Python ${{ matrix.python-version }}",
                            "uses": "actions/setup-python@v2",
                            "with": {"python-version": "${{ matrix.python-version }}"},
                        },
                        *bootstrap_caches(),
                        {
                            "name": "Set env vars",
                            "run": 'echo \'PANTS_CONFIG_FILES=+["${{ github.workspace }}/pants.ci.toml", "${{ github.workspace }}/pants.remote-cache.toml"]\' >> ${GITHUB_ENV}\n',
                        },
                        {"name": "Bootstrap Pants", "run": "./pants --version\n"},
                        {
                            "name": "Run smoke tests",
                            "run": "./pants help goals\n./pants list ::\n./pants roots\n./pants help targets\n",
                        },
                        {
                            "name": "Test and Lint Rust",
                            "run": "sudo apt-get install -y pkg-config fuse libfuse-dev\n./cargo clippy --all\n# We pass --tests to skip doc tests because our generated protos contain invalid\n# doc tests in their comments.\n./cargo test --all --tests -- --nocapture\n",
                            "if": "!contains(env.COMMIT_MESSAGE, '[ci skip-rust]')",
                        },
                        *native_engine_so_upload(),
                    ],
                },
                "test_python_linux": {
                    "name": "Test Python (Linux)",
                    "runs-on": "ubuntu-20.04",
                    "needs": "bootstrap_pants_linux",
                    "strategy": {"matrix": {"python-version": ["3.7.10"]}},
                    "steps": [
                        *checkout(),
                        {
                            "name": "Set up Python ${{ matrix.python-version }}",
                            "uses": "actions/setup-python@v2",
                            "with": {"python-version": "${{ matrix.python-version }}"},
                        },
                        *pants_virtualenv_cache(),
                        *native_engine_so_download(),
                        *pants_config_files(),
                        {"name": "Run Python tests", "run": "./pants test ::\n"},
                    ],
                },
                "lint_python_linux": {
                    "name": "Lint Python (Linux)",
                    "runs-on": "ubuntu-20.04",
                    "needs": "bootstrap_pants_linux",
                    "strategy": {"matrix": {"python-version": ["3.7.10"]}},
                    "steps": [
                        *checkout(),
                        {
                            "name": "Set up Python ${{ matrix.python-version }}",
                            "uses": "actions/setup-python@v2",
                            "with": {"python-version": "${{ matrix.python-version }}"},
                        },
                        *pants_virtualenv_cache(),
                        *native_engine_so_download(),
                        *pants_config_files(),
                        {
                            "name": "Lint",
                            "run": "./pants validate '**'\n./pants lint typecheck ::\n",
                        },
                    ],
                },
                "bootstrap_pants_macos": {
                    "name": "Bootstrap Pants, test Rust (MacOS)",
                    "runs-on": "macos-10.15",
                    "strategy": {"matrix": {"python-version": ["3.7.10"]}},
                    "env": {"rust_version": "1.49.0"},
                    "steps": [
                        *checkout(),
                        {
                            "name": "Set up Python ${{ matrix.python-version }}",
                            "uses": "actions/setup-python@v2",
                            "with": {"python-version": "${{ matrix.python-version }}"},
                        },
                        *bootstrap_caches(),
                        *pants_config_files(),
                        {"name": "Bootstrap Pants", "run": "./pants --version\n"},
                        *native_engine_so_upload(),
                        {
                            "name": "Test Rust",
                            "run": "# We pass --tests to skip doc tests because our generated protos contain invalid\n# doc tests in their comments.\n# We do not pass --all as BRFS tests don't pass on GHA MacOS containers.\n./cargo test --tests -- --nocapture\n",
                            "if": "!contains(env.COMMIT_MESSAGE, '[ci skip-rust]')",
                            "env": {"TMPDIR": "${{ runner.temp }}"},
                        },
                    ],
                },
                "test_python_macos": {
                    "name": "Test Python (MacOS)",
                    "runs-on": "macos-10.15",
                    "needs": "bootstrap_pants_macos",
                    "strategy": {"matrix": {"python-version": ["3.7.10"]}},
                    "steps": [
                        {"name": "Check out code", "uses": "actions/checkout@v2"},
                        {
                            "name": "Set up Python ${{ matrix.python-version }}",
                            "uses": "actions/setup-python@v2",
                            "with": {"python-version": "${{ matrix.python-version }}"},
                        },
                        *pants_virtualenv_cache(),
                        *native_engine_so_download(),
                        *pants_config_files(),
                        {
                            "name": "Run Python tests",
                            "run": "./pants --tag=+platform_specific_behavior test ::\n",
                        },
                    ],
                },
            },
        },
        Dumper=NoAliasDumper,
    )
    return {Path(".github/workflows/test.yaml"): f"{HEADER}\n\n{test_yaml}"}


def main() -> None:
    args = create_parser().parse_args()
    generated_yaml = generate()
    if args.check:
        for path, content in generated_yaml.items():
            if path.read_text() != content:
                die(f"Error: Generated path mismatched: {path}")
    else:
        for path, content in generated_yaml.items():
            path.write_text(content)


if __name__ == "__main__":
    main()
