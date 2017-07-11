# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import OrderedDict, namedtuple
from hashlib import sha1

import six
from twitter.common.dirutil import Fileset

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PayloadField, PrimitiveField, combine_hashes
from pants.base.validation import assert_list
from pants.build_graph.target import Target
from pants.fs import archive as Archive
from pants.source.wrapped_globs import FilesetWithSpec
from pants.util.dirutil import fast_relpath
from pants.util.memo import memoized_property


class RelativeToMapper(object):
  """A mapper that maps filesystem paths specified relative to a base directory."""

  def __init__(self, base):
    """The base directory paths should be mapped from."""
    self.base = base

  def __call__(self, path):
    return os.path.relpath(path, self.base)

  def __repr__(self):
    return 'IdentityMapper({})'.format(self.base)

  def __hash__(self):
    return hash(self.base)


class DirectoryReMapper(object):
  """A mapper that maps files relative to a base directory into a destination directory."""

  class NonexistentBaseError(Exception):
    pass

  def __init__(self, base, dest):
    """The base directory files should be mapped from, and the dest they should be mapped to.

    :param string base: the relative path to get_buildroot()
    :param string dest: the dest path in the bundle
    """
    self.base = os.path.abspath(os.path.join(get_buildroot(), base))
    if not os.path.isdir(self.base):
      raise DirectoryReMapper.NonexistentBaseError(
        'Could not find a directory to bundle relative to {0}'.format(self.base))
    self.dest = dest

  def __call__(self, path):
    return os.path.join(self.dest, os.path.relpath(path, self.base))

  def __repr__(self):
    return 'DirectoryReMapper({0}, {1})'.format(self.base, self.dest)


class BundleProps(namedtuple('_BundleProps', ['rel_path', 'mapper', 'fileset'])):
  @memoized_property
  def filemap(self):
    filemap = OrderedDict()
    if self.fileset is not None:
      paths = self.fileset() if isinstance(self.fileset, Fileset) \
          else self.fileset if hasattr(self.fileset, '__iter__') \
          else [self.fileset]
      for path in paths:
        abspath = path
        if not os.path.isabs(abspath):
          abspath = os.path.join(get_buildroot(), self.rel_path, path)
        filemap[abspath] = self.mapper(abspath)
    return filemap

  def __hash__(self):
    # Leave out fileset from hash calculation since it may not be hashable.
    return hash((self.rel_path, self.mapper))


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

  def __init__(self, parse_context):
    self._parse_context = parse_context

  def __call__(self, rel_path=None, mapper=None, relative_to=None, fileset=None):
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

    if fileset is None:
      raise ValueError("In {}:\n  Bare bundle() declarations without a `fileset=` parameter "
                       "are no longer supported.".format(self._parse_context.rel_path))

    if mapper and relative_to:
      raise ValueError("Must specify exactly one of 'mapper' or 'relative_to'")

    if rel_path and isinstance(fileset, FilesetWithSpec) and fileset.rel_root != rel_path:
      raise ValueError("Must not use a glob for 'fileset' with 'rel_path'."
                       " Globs are eagerly evaluated and ignore 'rel_path'.")

    # A fileset is either a glob, a string or a list of strings.
    if isinstance(fileset, FilesetWithSpec):
      pass
    elif isinstance(fileset, six.string_types):
      fileset = [fileset]
    else:
      fileset = assert_list(fileset, key_arg='fileset')

    real_rel_path = rel_path or self._parse_context.rel_path

    if relative_to:
      base = os.path.join(get_buildroot(), real_rel_path, relative_to)
      mapper = RelativeToMapper(base)
    else:
      mapper = mapper or RelativeToMapper(os.path.join(get_buildroot(), real_rel_path))

    return BundleProps(real_rel_path, mapper, fileset)

  def create_bundle_props(self, bundle):
    rel_path = getattr(bundle, 'rel_path', None)
    mapper = getattr(bundle, 'mapper', None)
    relative_to = getattr(bundle, 'relative_to', None)
    fileset = getattr(bundle, 'fileset', None)
    return self(rel_path, mapper, relative_to, fileset)


class BundleField(tuple, PayloadField):
  """A tuple subclass that mixes in PayloadField.

  Must be initialized with an iterable of Bundle instances.
  """

  @staticmethod
  def _hash_bundle(bundle):
    hasher = sha1()
    hasher.update(bundle.rel_path)
    for abs_path in sorted(bundle.filemap.keys()):
      buildroot_relative_path = os.path.relpath(abs_path, get_buildroot())
      hasher.update(buildroot_relative_path)
      hasher.update(bundle.filemap[abs_path])
      if os.path.isfile(abs_path):
        # Update with any additional string to differentiate empty file with non-existing file.
        hasher.update('e')
        with open(abs_path, 'rb') as f:
          hasher.update(f.read())
    return hasher.hexdigest()

  def _compute_fingerprint(self):
    return combine_hashes(map(BundleField._hash_bundle, self))


class JvmApp(Target):
  """A deployable JVM application.

  Invoking the ``bundle`` goal on one of these targets creates a
  self-contained artifact suitable for deployment on some other machine.
  The artifact contains the executable jar, its dependencies, and
  extra files like config files, startup scripts, etc.

  :API: public
  """
  class InvalidArchiveType(Exception):
    """Raised when archive type defined in Target is invalid"""

  def __init__(self,
               name=None,
               payload=None,
               binary=None,
               bundles=None,
               basename=None,
               deployjar=None,
               archive=None,
               **kwargs):
    """
    :param string binary: Target spec of the ``jvm_binary`` that contains the
      app main.
    :param bundles: One or more ``bundle``\s
      describing "extra files" that should be included with this app
      (e.g.: config files, startup scripts).
    :param string basename: Name of this application, if different from the
      ``name``. Optionally pants uses this in the ``bundle`` goal to name the distribution
      artifact.  Note this is unsafe because of the possible conflict when multiple bundles
      are built.
    :param boolean deployjar: If True, pack all 3rdparty and internal jar classfiles into
      a single deployjar in the bundle's root dir. If unset, all jars will go into the
      bundle's libs directory, the root will only contain a synthetic jar with its manifest's
      Class-Path set to those jars.
    :param string archive: Create an archive of this type from the bundle.
    """
    if archive and archive not in Archive.TYPE_NAMES:
      raise self.InvalidArchiveType(
        'Given archive type "{}" is invalid, choose from {}.'.format(archive, list(Archive.TYPE_NAMES)))

    payload = payload or Payload()
    payload.add_fields({
      'basename': PrimitiveField(basename or name),
      'binary': PrimitiveField(binary),
      'bundles': BundleField(bundles or []),
      'deployjar': PrimitiveField(deployjar),
      'archive': PrimitiveField(archive),
      })
    super(JvmApp, self).__init__(name=name, payload=payload, **kwargs)

    if name == basename:
      raise TargetDefinitionException(self, 'basename must not equal name.')

  def globs_relative_to_buildroot(self):
    buildroot = get_buildroot()
    globs = []
    for bundle in self.bundles:
      fileset = bundle.fileset
      if fileset is None:
        continue
      elif hasattr(fileset, 'filespec'):
        globs += bundle.fileset.filespec['globs']
      else:
        # NB(nh): filemap is an OrderedDict, so this ordering is stable.
        globs += [fast_relpath(f, buildroot) for f in bundle.filemap.keys()]
    super_globs = super(JvmApp, self).globs_relative_to_buildroot()
    if super_globs:
      globs += super_globs['globs']
    return {'globs': globs}

  @classmethod
  def compute_dependency_specs(cls, kwargs=None, payload=None):
    for spec in super(JvmApp, cls).compute_dependency_specs(kwargs, payload):
      yield spec

    target_representation = kwargs or payload.as_dict()
    binary = target_representation.get('binary')
    if binary:
      yield binary

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
