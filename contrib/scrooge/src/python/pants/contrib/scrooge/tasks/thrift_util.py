# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re


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


def calculate_include_paths(targets, is_thrift_target):
  """Calculates the set of import paths for the given targets.

  :targets: The targets to examine.
  :is_thrift_target: A predicate to pick out thrift targets for consideration in the analysis.

  :returns: Include basedirs for the target.
  """

  basedirs = set()
  def collect_paths(target):
    basedirs.add(target.target_base)

  for target in targets:
    target.walk(collect_paths, predicate=is_thrift_target)
  return basedirs
