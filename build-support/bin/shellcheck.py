#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import shutil
import subprocess
from glob import glob

from common import die, green


def main() -> None:
  ensure_shellcheck_installed()
  run_shellcheck()


def ensure_shellcheck_installed() -> None:
  if shutil.which("shellcheck") is None:
    die("`shellcheck` not installed! You may download this through your operating system's "
        "package manager, such as brew, apt, or yum. See "
        "https://github.com/koalaman/shellcheck#installing.")


def run_shellcheck() -> None:
  targets = glob("./build-support/bin/*.sh") + glob("./build-support/bin/native/*.sh") + [
    "./pants",
    "./pants2",
    "./build-support/common.sh",
    "./build-support/pants-intellij.sh",
    "./build-support/pants_venv",
    "./build-support/virtualenv",
    "./build-support/githooks/pre-commit",
    "./build-support/githooks/prepare-commit-msg",
    "./build-support/python/clean.sh",
  ]
  command = ["shellcheck", "--shell=bash", "--external-sources"] + targets
  try:
    subprocess.run(command, check=True)
  except subprocess.CalledProcessError:
    die("Please fix the above errors and run again.")
  else:
    green("./pants passed the shellcheck!")


if __name__ == "__main__":
  main()
