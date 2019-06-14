#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess


def main() -> None:
  subprocess.run(["./pants", "--tag=+type_checked", "mypy", "::"], check=True)


if __name__ == '__main__':
  main()
