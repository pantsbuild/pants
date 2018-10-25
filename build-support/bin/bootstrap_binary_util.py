#!/usr/bin/env python2.7
# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Helper for download_binary.sh to use BinaryUtil to download the appropriate binaries.
#
# usage: bootstrap_binary_util.py util_name version filename

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
import sys
from functools import reduce

from pants.binaries.binary_util import BinaryRequest, BinaryUtil
from pants.fs.archive import archiver_for_path
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.subsystem.subsystem import Subsystem


def main():
  util_name, version, filename = tuple(sys.argv[1:])
  options_bootstrapper = OptionsBootstrapper()
  subsystems = (GlobalOptionsRegistrar, BinaryUtil.Factory)
  known_scope_infos = reduce(set.union, (ss.known_scope_infos() for ss in subsystems), set())
  options = options_bootstrapper.get_full_options(known_scope_infos)
  for subsystem in subsystems:
    subsystem.register_options_on_scope(options)
  Subsystem.set_options(options)

  # If the filename provided ends in a known archive extension (such as ".tar.gz"), then we get the
  # appropriate Archiver to pass to BinaryUtil.
  archiver_for_current_binary = None
  try:
    archiver_for_current_binary = archiver_for_path(filename)
    # BinaryRequest requires the `name` field to be provided without an extension, as it appends the
    # archiver's extension if one is provided, so we have to remove it here.
    filename = re.sub(
      r'\.{}\Z'.format(re.escape(archiver_for_current_binary.extension)),
      '',
      filename)
  except ValueError:
    pass

  binary_util = BinaryUtil.Factory.create()
  binary_request = BinaryRequest(
    supportdir='bin/{}'.format(util_name),
    version=version,
    name=filename,
    platform_dependent=True,
    external_url_generator=None,
    archiver=archiver_for_current_binary)
  path = binary_util.select(binary_request)

  print(path)


if __name__ == '__main__':
  main()
