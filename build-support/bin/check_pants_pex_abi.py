#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Check that the ./pants.pex was built using the passed abi specification.

import argparse
import json
import zipfile
from pathlib import Path

from common import die, green


def main() -> None:
  if not Path("pants.pex").is_file:
    die("pants.pex not found! Ensure you are in the repository root, then run " \
        "'./build-support/bin/ci.sh -b' to bootstrap pants.pex with Python 3 or " \
        "'./build-support/bin/ci.sh -2b' to bootstrap pants.pex with Python 2.")
  expected_abis = frozenset(create_parser().parse_args().abis)
  with zipfile.ZipFile("pants.pex", "r") as pex:
    with pex.open("PEX-INFO", "r") as pex_info:
      pex_info_content = pex_info.readline().decode()
  parsed_abis = frozenset(
    parse_abi_from_filename(filename)
    for filename in json.loads(pex_info_content)["distributions"].keys()
    if parse_abi_from_filename(filename) != "none"
  )
  if not parsed_abis.issubset(expected_abis):
    die("pants.pex was built with the incorrect ABI. Expected wheels with: {}, found: {}."
        .format(' or '.join(sorted(expected_abis)), ', '.join(sorted(parsed_abis))))
  green("Success. The pants.pex was built with wheels carrying the expected ABIs: {}."
          .format(', '.join(sorted(parsed_abis))))


def create_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Check that ./pants.pex was built using the passed abi specification."
  )
  parser.add_argument("abis", nargs="+", help="The expected abis, e.g. `cp27m` or `abi3 cp36m`")
  return parser


def parse_abi_from_filename(filename: str) -> str:
  """This parses out the abi from a wheel filename.

  For example, `configparser-3.5.0-py2-abi3-any.whl` would return `abi3`.
  See https://www.python.org/dev/peps/pep-0425/#use for how wheel filenames are defined."""
  return filename.split("-")[-2]


if __name__ == "__main__":
  main()
