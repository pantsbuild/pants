# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from functools import partial

from twitter.common.collections import maybe_list
from twitter.common.dirutil import Fileset
from twitter.common.lang import Compatibility

from pants.base.build_environment import get_buildroot
from pants.base.build_manual import manual
from pants.base.payload import BundlePayload
from pants.base.target import Target
from pants.base.exceptions import TargetDefinitionException
from pants.targets.jvm_target import JvmTarget


@manual.builddict(tags=["jvm"])
class JvmBinary(JvmTarget):
  """Produces a JVM binary optionally identifying a launcher main class.

  Below are a summary of how key goals affect targets of this type:

  * ``bundle`` - Creates a self-contained directory with the binary and all
    its dependencies, optionally archived, suitable for deployment.
  * ``binary`` - Create an executable jar of the binary. On the JVM
    this means the jar has a manifest specifying the main class.
  * ``run`` - Executes the main class of this binary locally.
  """
  def __init__(self,
               name=None,
               main=None,
               basename=None,
               source=None,
               deploy_excludes=None,
               **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param string main: The name of the ``main`` class, e.g.,
      ``'com.pants.examples.hello.main.HelloMain'``. This class may be
      present as the source of this target or depended-upon library.
    :param string basename: Base name for the generated ``.jar`` file, e.g.,
      ``'hello'``. (By default, uses ``name`` param)
    :param string source: Name of one ``.java`` or ``.scala`` file (a good
      place for a ``main``).
    :param resources: List of ``resource``\s to include in bundle.
    :param dependencies: List of targets (probably ``java_library`` and
     ``scala_library`` targets) to "link" in.
    :param excludes: List of ``exclude``\s to filter this target's transitive
     dependencies against.
    :param deploy_excludes: List of ``excludes`` to apply at deploy time.
      If you, for example, deploy a java servlet that has one version of
      ``servlet.jar`` onto a Tomcat environment that provides another version,
      they might conflict. ``deploy_excludes`` gives you a way to build your
      code but exclude the conflicting ``jar`` when deploying.
    :param configurations: Ivy configurations to resolve for this target.
      This parameter is not intended for general use.
    :type configurations: tuple of strings
    """
    sources = [source] if source else None
    super(JvmBinary, self).__init__(name=name, sources=sources, **kwargs)

    if main and not isinstance(main, Compatibility.string):
      raise TargetDefinitionException(self, 'main must be a fully qualified classname')

    if source and not isinstance(source, Compatibility.string):
      raise TargetDefinitionException(self, 'source must be a single relative file path')

    self.main = main
    self.basename = basename or name
    self.deploy_excludes = deploy_excludes or []


class RelativeToMapper(object):
  """A mapper that maps files specified relative to a base directory."""

  def __init__(self, base):
    """The base directory files should be mapped from."""
    self.base = base

  def __call__(self, file):
    return os.path.relpath(file, self.base)

  def __repr__(self):
    return 'IdentityMapper(%s)' % self.base

  def __hash__(self):
    return hash(self.base)


@manual.builddict(tags=["jvm"])
class Bundle(object):
  """A set of files to include in an application bundle.

  Looking for Java-style resources accessible via the ``Class.getResource`` API?
  Those are :ref:`bdict_resources`\ .

  Files added to the bundle will be included when bundling an application target.
  By default relative paths are preserved. For example, to include ``config``
  and ``scripts`` directories: ::

    bundles=[
      bundle().add(rglobs('config/*', 'scripts/*')),
    ]

  To include files relative to some path component use the ``relative_to`` parameter.
  The following places the contents of ``common/config`` in a  ``config`` directory
  in the bundle. ::

    bundles=[
      bundle(relative_to='common').add(globs('common/config/*'))
    ]
  """

  def __init__(self, rel_path=None, mapper=None, relative_to=None):
    """
    :param rel_path: Base path of the "source" file paths. By default, path of the
      BUILD file. Useful for assets that don't live in the source code repo.
    :param mapper: Function that takes a path string and returns a path string. Takes a path in
      the source tree, returns a path to use in the resulting bundle. By default, an identity
      mapper.
    :param string relative_to: Set up a simple mapping from source path to bundle path.
      E.g., ``relative_to='common'`` removes that prefix from all files in the application bundle.
    """
    if mapper and relative_to:
      raise ValueError("Must specify exactly one of 'mapper' or 'relative_to'")

    self._rel_path = rel_path

    if relative_to:
      base = os.path.join(get_buildroot(), self._rel_path, relative_to)
      if not os.path.isdir(os.path.join(get_buildroot(), base)):
        raise ValueError('Could not find a directory to bundle relative to at %s' % base)
      self.mapper = RelativeToMapper(base)
    else:
      self.mapper = mapper or RelativeToMapper(os.path.join(get_buildroot(), self._rel_path))

    self.filemap = {}

  @manual.builddict()
  def add(self, *filesets):
    """Add files to the bundle, where ``filesets`` is a filename, ``globs``, or ``rglobs``.
    Note this is a variable length param and may be specified any number of times.
    """

    for fileset in filesets:
      paths = fileset() if isinstance(fileset, Fileset) \
                        else fileset if hasattr(fileset, '__iter__') \
                        else [fileset]
      for path in paths:
        abspath = path
        if not os.path.isabs(abspath):
          abspath = os.path.join(get_buildroot(), self._rel_path, path)
        if not os.path.exists(abspath):
          raise ValueError('Given path: %s with absolute path: %s which does not exist'
                           % (path, abspath))
        self.filemap[abspath] = self.mapper(abspath)
    return self

  def __repr__(self):
    return 'Bundle(%s, %s)' % (self.mapper, self.filemap)


@manual.builddict(tags=["jvm"])
class JvmApp(Target):
  """A JVM-based application consisting of a binary plus "extra files".

  Invoking the ``bundle`` goal on one of these targets creates a
  self-contained artifact suitable for deployment on some other machine.
  The artifact contains the executable jar, its dependencies, and
  extra files like config files, startup scripts, etc.
  """

  def __init__(self, name=None, bundles=None, basename=None, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param bundles: One or more :class:`pants.targets.jvm_binary.Bundle`'s
      describing "extra files" that should be included with this app
      (e.g.: config files, startup scripts).
    :param string basename: Name of this application, if different from the
      ``name``. Pants uses this in the ``bundle`` goal to name the distribution
      artifact. In most cases this parameter is not necessary.
    """
    payload = BundlePayload(bundles)
    super(JvmApp, self).__init__(name=name, payload=payload, **kwargs)

    if name == basename:
      raise TargetDefinitionException(self, 'basename must not equal name.')
    self.basename = basename or name

  @property
  def bundles(self):
    return self.payload.bundles

  @property
  def binary(self):
    # TODO(pl): Assert there is only one dep and it is a JvmBinary
    return self.dependencies[0]

  @property
  def jar_dependencies(self):
    return self.binary.jar_dependencies

  def is_jvm_app(self):
    return True
