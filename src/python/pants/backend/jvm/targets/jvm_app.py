# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.dirutil import Fileset

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.base.build_environment import get_buildroot
from pants.base.build_manual import manual
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import BundleField, PrimitiveField
from pants.build_graph.target import Target


class RelativeToMapper(object):
  """A mapper that maps files specified relative to a base directory."""

  def __init__(self, base):
    """The base directory files should be mapped from."""
    self.base = base

  def __call__(self, file):
    return os.path.relpath(file, self.base)

  def __repr__(self):
    return 'IdentityMapper({})'.format(self.base)

  def __hash__(self):
    return hash(self.base)


class DirectoryReMapper(object):
  """A mapper that maps files relative to a base directory into a destination directory."""

  class BaseNotExistsError(Exception):
    "The base directory does not exist error"

  def __init__(self, base, dest):
    """The base directory files should be mapped from, and the dest they should be mapped to.

    :param string base: the relative path to get_buildroot()
    :param string dest: the dest path in the bundle
    """
    self.base = os.path.abspath(os.path.join(get_buildroot(), base))
    if not os.path.isdir(self.base):
      raise DirectoryReMapper.BaseNotExistsError(
        'Could not find a directory to bundle relative to {0}'.format(self.base))
    self.dest = dest

  def __call__(self, path):
    return os.path.join(self.dest, os.path.relpath(path, self.base))

  def __repr__(self):
    return 'DirectoryReMapper({0}, {1})'.format(self.base, self.dest)


class Bundle(object):
  """A set of files to include in an application bundle.

  To learn about application bundles, see
  `bundles <JVMProjects.html#jvm-bundles>`_.
  Looking for Java-style resources accessible via the ``Class.getResource`` API?
  Those are `resources <build_dictionary.html#resources>`_.

  Files added to the bundle will be included when bundling an application target.
  By default relative paths are preserved. For example, to include ``config``
  and ``scripts`` directories: ::

    bundles=[
      bundle(fileset=[rglobs('config/*', 'scripts/*'), 'my.cfg']),
    ]

  To include files relative to some path component use the ``relative_to`` parameter.
  The following places the contents of ``common/config`` in a  ``config`` directory
  in the bundle. ::

    bundles=[
      bundle(relative_to='common', fileset=globs('common/config/*'))
    ]

  """

  @classmethod
  @manual.builddict(factory=True)
  def factory(cls, parse_context):
    """Return a factory method that can create bundles rooted at the parse context path."""
    def bundle(**kwargs):
      return Bundle(parse_context.rel_path, **kwargs)
    bundle.__doc__ = Bundle.__init__.__doc__
    return bundle

  def __init__(self, target_rel_path, rel_path=None, mapper=None, relative_to=None, fileset=None):
    """
    :param rel_path: Base path of the "source" file paths. By default, path of the
      BUILD file. Useful for assets that don't live in the source code repo.
    :param mapper: Function that takes a path string and returns a path string. Takes a path in
      the source tree, returns a path to use in the resulting bundle. By default, an identity
      mapper.
    :param string relative_to: Set up a simple mapping from source path to bundle path.
    :param fileset: The set of files to include in the bundle.  A string filename, or list of
      filenames, or a Fileset object (e.g. globs()).
      E.g., ``relative_to='common'`` removes that prefix from all files in the application bundle.
    """
    if mapper and relative_to:
      raise ValueError("Must specify exactly one of 'mapper' or 'relative_to'")

    self._rel_path = rel_path or target_rel_path
    self.filemap = {}

    if relative_to:
      base = os.path.join(get_buildroot(), self._rel_path, relative_to)
      self.mapper = RelativeToMapper(base)
    else:
      self.mapper = mapper or RelativeToMapper(os.path.join(get_buildroot(), self._rel_path))

    if fileset is not None:
      self._add([fileset])
    self.fileset = fileset

  def _add(self, filesets):
    for fileset in filesets:
      paths = fileset() if isinstance(fileset, Fileset) \
        else fileset if hasattr(fileset, '__iter__') \
        else [fileset]
      for path in paths:
        abspath = path
        if not os.path.isabs(abspath):
          abspath = os.path.join(get_buildroot(), self._rel_path, path)
        self.filemap[abspath] = self.mapper(abspath)
    return self

  def __repr__(self):
    return 'Bundle({}, {})'.format(self.mapper, self.filemap)


class JvmApp(Target):
  """A JVM-based application consisting of a binary plus "extra files".

  Invoking the ``bundle`` goal on one of these targets creates a
  self-contained artifact suitable for deployment on some other machine.
  The artifact contains the executable jar, its dependencies, and
  extra files like config files, startup scripts, etc.
  """

  def __init__(self, name=None, payload=None, binary=None, bundles=None, basename=None, **kwargs):
    """
    :param string binary: Target spec of the ``jvm_binary`` that contains the
      app main.
    :param bundles: One or more ``bundle``\s
      describing "extra files" that should be included with this app
      (e.g.: config files, startup scripts).
    :param string basename: Name of this application, if different from the
      ``name``. Pants uses this in the ``bundle`` goal to name the distribution
      artifact. In most cases this parameter is not necessary.
    """
    payload = payload or Payload()
    payload.add_fields({
      'basename': PrimitiveField(basename or name),
      'binary': PrimitiveField(binary),
      'bundles': BundleField(bundles or []),
      })
    super(JvmApp, self).__init__(name=name, payload=payload, **kwargs)

    if name == basename:
      raise TargetDefinitionException(self, 'basename must not equal name.')

  def globs_relative_to_buildroot(self):
    globs = []
    for bundle in self.bundles:
      fileset = bundle.fileset
      if fileset is None:
        continue
      elif hasattr(fileset, 'filespec'):
        globs += bundle.fileset.filespec['globs']
      else:
        globs += bundle.fileset
    super_globs = super(JvmApp, self).globs_relative_to_buildroot()
    if super_globs:
      globs += super_globs['globs']
    return {'globs': globs}

  @property
  def traversable_dependency_specs(self):
    for spec in super(JvmApp, self).traversable_dependency_specs:
      yield spec
    if self.payload.binary:
      yield self.payload.binary

  @property
  def basename(self):
    return self.payload.basename

  @property
  def bundles(self):
    return self.payload.bundles

  @property
  def binary(self):
    """:returns: The JvmBinary instance this JvmApp references.
    :rtype: JvmBinary
    """
    dependencies = self.dependencies
    if len(dependencies) != 1:
      raise TargetDefinitionException(self, 'A JvmApp must define exactly one JvmBinary '
                                            'dependency, have: {}'.format(dependencies))
    binary = dependencies[0]
    if not isinstance(binary, JvmBinary):
      raise TargetDefinitionException(self, 'Expected JvmApp binary dependency to be a JvmBinary '
                                            'target, found {}'.format(binary))
    return binary

  @property
  def jar_dependencies(self):
    return self.binary.jar_dependencies
