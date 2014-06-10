# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import os
import re
import shutil

from twitter.common import log
from twitter.common.collections import OrderedSet
from twitter.common.contextutil import open_tar
from twitter.common.contextutil import open_zip
from twitter.common.contextutil import temporary_dir
from twitter.common.contextutil import temporary_file_path
from twitter.common.dirutil import safe_rmtree
from twitter.common.dirutil.fileset import Fileset
from twitter.common.lang import Compatibility

from pants.base.address import parse_spec
from pants.base.build_environment import get_buildroot
from pants.base.build_manual import manual
from pants.fs.archive import archiver


def get_archive_root():
  """Gets the directory which JarFileset expects ivy to stick imports jars in."""
  return os.path.join(get_buildroot(), '.pants.d', 'archives', 'jars')


@manual.builddict(tags=["java"])
def jar_sources(*jar_deps):
  """Creates JarFilesets for use in protobuf imports.

  :param jar_deps: varargs list of jar() objects and/or strings storing spec-paths to jar_library
    targets containing jar() objects (for use with the 3rdparty pattern).
  :returns: a callable which takes in a Context and a BuildFile and returns a list of (JarFileset,
    JarDependency) tuples for each JarDependency input argument.
  """
  def expand_jar_dep(context, build_file, jar_dep):
    # isinstance is ugly in general, but this is the way build_file_parser.py does it so it seems
    # reasonable to do the same.
    if isinstance(jar_dep, Compatibility.string):
      # Need to grab JarLibrary
      try:
        for library in context.resolve(':'.join(parse_spec(jar_dep, relative_to=build_file.spec_path))):
          for jar in library.jar_dependencies:
            yield jar
      except Exception as e:
        raise JarSourcesError('Failed to expand jar_library spec "{spec}": {error}'
                              .format(spec=jar_dep, error=str(e)))
      return
    yield jar_dep

  def resolve_jar_pairs(context, build_file):
    real_deps = []
    for jar_dep in jar_deps:
      real_deps.extend(expand_jar_dep(context, build_file, jar_dep))
    return [(JarFileset(jar_dep), jar_dep) for jar_dep in real_deps]

  return resolve_jar_pairs


class JarSourcesError(Exception):
  """Error which is raised if there is a problem fetching the jarred protos."""


class JarFileset(Fileset):
  """Takes in a JarDependency and returns a fileset which iterates over its contents."""

  def __init__(self, jar_dep):
    super(JarFileset, self).__init__(self._expand_directory)
    self._jar = jar_dep
    self._dir = os.path.join('.pants.d', 'extracted', jar_dep.org, jar_dep.name, jar_dep.rev)
    # Probably not the best way to do this. See also ivy_imports.py.
    self._jar_path = os.path.join(get_archive_root(), jar_dep.org, jar_dep.name, 'jars',
                                  jar_dep.name + '-' + jar_dep.rev + '.jar')
    self._jar_path = os.path.relpath(self._jar_path, get_buildroot())
    if not os.path.exists(self._jar_path):
      # If the jar doesn't exist, ivy hasn't gotten it yet, so we shouldn't have a folder for
      # extracted files yet. Which means this is leftover from a past run, so nuke it.
      safe_rmtree(self._dir)

  def _expand_directory(self):
    if not os.path.exists(self._dir):
      if not os.path.exists(self._jar_path):
        raise JarSourcesError('Never got the jar file from ivy! ({jar})'.format(jar=self._jar_path))
      archiver('zip').extract(self._jar_path, self._dir)
    return [self._dir]
