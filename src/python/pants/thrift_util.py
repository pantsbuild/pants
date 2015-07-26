# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.binary_util import BinaryUtil
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


INCLUDE_PARSER = re.compile(r'^\s*include\s+"([^"]+)"\s*([\/\/|\#].*)*$')


def find_includes(basedirs, source, log=None):
  """Finds all thrift files included by the given thrift source.

  :basedirs: A set of thrift source file base directories to look for includes in.
  :source: The thrift source file to scan for includes.
  :log: An optional logger
  """

  all_basedirs = [os.path.dirname(source)]
  all_basedirs.extend(basedirs)

  includes = set()
  with open(source, 'r') as thrift:
    for line in thrift.readlines():
      match = INCLUDE_PARSER.match(line)
      if match:
        capture = match.group(1)
        added = False
        for basedir in all_basedirs:
          include = os.path.join(basedir, capture)
          if os.path.exists(include):
            if log:
              log.debug('{} has include {}'.format(source, include))
            includes.add(include)
            added = True
        if not added:
          raise ValueError("{} included in {} not found in bases {}"
                           .format(include, source, all_basedirs))
  return includes


def find_root_thrifts(basedirs, sources, log=None):
  """Finds the root thrift files in the graph formed by sources and their recursive includes.

  :basedirs: A set of thrift source file base directories to look for includes in.
  :sources: Seed thrift files to examine.
  :log: An optional logger.
  """

  root_sources = set(sources)
  for source in sources:
    root_sources.difference_update(find_includes(basedirs, source, log=log))
  return root_sources


def calculate_compile_sources(targets, is_thrift_target):
  """Calculates the set of thrift source files that need to be compiled.
  It does not exclude sources that are included in other sources.

  A tuple of (include basedirs, thrift sources) is returned.

  :targets: The targets to examine.
  :is_thrift_target: A predicate to pick out thrift targets for consideration in the analysis.
  """

  basedirs = set()
  sources = set()
  def collect_sources(target):
    basedirs.add(target.target_base)
    sources.update(target.sources_relative_to_buildroot())

  for target in targets:
    target.walk(collect_sources, predicate=is_thrift_target)
  return basedirs, sources


# TODO(John Sirois): Extract this subsystem to its own file.
class ThriftBinary(object):
  """Encapsulates access to pre-built thrift static binaries."""

  class Factory(Subsystem):
    options_scope = 'thrift-binary'

    @classmethod
    def dependencies(cls):
      return (BinaryUtil.Factory,)

    @classmethod
    def register_options(cls, register):
      register('--supportdir', recursive=True, advanced=True, default='bin/thrift',
               help='Find thrift binaries under this dir.   Used as part of the path to lookup the'
                    'tool with --binary-util-baseurls and --pants-bootstrapdir')
      register('--version', recursive=True, advanced=True, default='0.9.2',
               help='Thrift compiler version.   Used as part of the path to lookup the'
                    'tool with --binary-util-baseurls and --pants-bootstrapdir')

    def create(self):
      # NB: create is an instance method to allow the user to choose global or scoped.
      # Its not unreasonable to imagine python and jvm stacks using different versions.
      binary_util = BinaryUtil.Factory.create()
      options = self.get_options()
      return ThriftBinary(binary_util, options.supportdir, options.version)

  def __init__(self, binary_util, relpath, version):
    self._binary_util = binary_util
    self._relpath = relpath
    self._version = version

  @property
  def version(self):
    """Returns the version of the thrift binary.

    :returns string version: The thrift version number string.
    """
    return self._version

  @memoized_property
  def path(self):
    """Selects a thrift compiler binary matching the current os and architecture.

    :returns: The absolute path to a locally bootstrapped thrift compiler binary.
    """
    return self._binary_util.select_binary(self._relpath, self.version, 'thrift')
