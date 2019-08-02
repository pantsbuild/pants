#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess


def main() -> None:
  subprocess.run(["./pants", "--lint-skip", "--no-lint-mypy-skip", "--tag=+type_checked", "lint", "::"], check=True)


if __name__ == '__main__':
  main()
