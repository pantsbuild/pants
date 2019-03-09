#!/usr/bin/env python2.7
# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Check that the ./pants.pex was built using the passed abi specification.

from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import json
import os.path
import zipfile


def main():
  if not os.path.isfile("pants.pex"):
    die("pants.pex not found! Ensure you are in the repository root and run " \
        "'./build-support/bin/ci.sh -b' to bootstrap a pants.pex.")
  expected_abi = create_parser().parse_args().abi
  with zipfile.ZipFile("pants.pex", "r") as pex:
    with pex.open("PEX-INFO", "r") as pex_info:
      pex_info_content = str(pex_info.readline())
  parsed_abis = {
    parse_abi_from_filename(filename)
    for filename in json.loads(pex_info_content)["distributions"].keys()
    if parse_abi_from_filename(filename) != "none"
  }
  if len(parsed_abis) < 1:
    die("No abi tag found. Expected: {}.".format(expected_abi))
  elif len(parsed_abis) > 1:
    die("Multiple abi tags found. Expected: {}, found: {}.".format(expected_abi, parsed_abis))
  found_abi = list(parsed_abis)[0]
  if found_abi != expected_abi:
    die("pants.pex was built with the incorrect ABI. Expected: {}, found: {}.".format(expected_abi, found_abi))


def create_parser():
  parser = argparse.ArgumentParser(
    description="Check that ./pants.pex was built using the passed abi specification."
  )
  parser.add_argument("abi", help="The expected abi, e.g. `cp27m` or `abi3`")
  return parser


def parse_abi_from_filename(filename):
  """This parses out the abi from a wheel filename.

  For example, `configparser-3.5.0-py2-abi3-any.whl` would return `abi3`.
  See https://www.python.org/dev/peps/pep-0425/#use for how wheel filenames are defined."""
  return filename.split("-")[-2]


def die(message):
  red = "\033[31m"
  reset = "\033[0m"
  raise SystemExit("{}{}{}".format(red, message, reset))


if __name__ == "__main__":
  main()
