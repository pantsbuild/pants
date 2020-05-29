#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import shutil
import subprocess
from glob import glob

from common import die


def main() -> None:
    ensure_shellcheck_installed()
    run_shellcheck()


def ensure_shellcheck_installed() -> None:
    if shutil.which("shellcheck") is None:
        die(
            "`shellcheck` not installed! You may download this through your operating system's "
            "package manager, such as brew, apt, or yum. See "
            "https://github.com/koalaman/shellcheck#installing."
        )


def run_shellcheck() -> None:
    targets = set(glob("./**/*.sh", recursive=True)) | {
        "./pants",
        "./build-support/pants_venv",
        "./build-support/virtualenv",
        "./build-support/githooks/pre-commit",
        "./build-support/githooks/prepare-commit-msg",
    }
    targets -= set(glob("./build-support/bin/native/src/**/*.sh", recursive=True))
    targets -= set(glob("./build-support/virtualenv.dist/**/*.sh", recursive=True))
    targets -= set(glob("./build-support/twine-deps.venv/**/*.sh", recursive=True))
    command = ["shellcheck", "--shell=bash", "--external-sources"] + sorted(targets)
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError:
        die("Please fix the above errors and run again.")


if __name__ == "__main__":
    main()
