# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)
from contextlib import contextmanager

import os
import platform
import zipfile

from twitter.common.collections.ordereddict import OrderedDict
from twitter.common.collections.orderedset import OrderedSet
from twitter.common.contextutil import temporary_dir

from pants.base.build_environment import get_version
from pants.base.exceptions import TaskError
from pants.fs.archive import ZIP
from pants.java.jar import Manifest, open_jar
from pants.targets.jvm_binary import JvmBinary
from pants.tasks.task import Task


class JvmBinaryTask(Task):

  @staticmethod
  def is_binary(target):
    return isinstance(target, JvmBinary)

  @staticmethod
  def create_main_manifest(binary):
    """Creates a jar manifest for the given binary.

    If the binary declares a main then a 'Main-Class' manifest entry will be included.
    """
    manifest = Manifest()
    manifest.addentry(Manifest.MANIFEST_VERSION, '1.0')
    manifest.addentry(Manifest.CREATED_BY,
                      'python %s pants %s' % (platform.python_version(), get_version()))
    main = binary.main or '*** java -jar not supported, please use -cp and pick a main ***'
    manifest.addentry(Manifest.MAIN_CLASS, main)
    return manifest

  def __init__(self, context, workdir):
    super(JvmBinaryTask, self).__init__(context, workdir)
    self.context.products.require('jars')
    self.context.products.require('jar_dependencies', predicate=self.is_binary)

  def list_external_jar_dependencies(self, binary, confs=None):
    """Returns the external jar dependencies of the given binary.

    :returns: An iterable of (basedir, jarfile) tuples where the jarfile names are
              guaranteed to be unique.
    """
    jardepmap = self.context.products.get('jar_dependencies') or {}
    if confs:
      return self._mapped_dependencies(jardepmap, binary, confs)
    else:
      return self._unexcluded_dependencies(jardepmap, binary)

  @contextmanager
  def monolithic_jar(self, binary, path, with_external_deps):
    """Creates a jar containing the class files for a jvm_binary target and all its deps.

    Yields a handle to the open jarfile, so the caller can add to the jar if needed.

    :param binary: The jvm_binary target to operate on.
    :param path: Write the output jar here, overwriting an existing file, if any.
    :param with_external_deps: If True, unpack external jar deps and add their classes to the jar.
    """
    # TODO(benjy): There's actually nothing here that requires 'binary' to be a jvm_binary.
    # It could be any target. And that might actually be useful.
    # TODO(benjy): Get the classfiles directly from the class products, instead of unpacking
    # the per-target jars?

    jarmap = self.context.products.get('jars')

    with open_jar(path, 'w', compression=zipfile.ZIP_DEFLATED) as jar:
      def add_jars(target):
        generated = jarmap.get(target)
        if generated:
          for base_dir, jars in generated.items():
            for internal_jar in jars:
              self._dump(os.path.join(base_dir, internal_jar), jar)

      with self.context.new_workunit(name='add-generated-jars'):
        binary.walk(add_jars)

      if with_external_deps:
        with self.context.new_workunit(name='add-dependency-jars'):
          for basedir, external_jar in self.list_external_jar_dependencies(binary):
            self._dump(os.path.join(basedir, external_jar), jar)

      yield jar

  def _dump(self, jar_path, jar_file):
    self.context.log.debug('  dumping %s' % jar_path)

    with temporary_dir() as tmpdir:
      try:
        ZIP.extract(jar_path, tmpdir)
      except zipfile.BadZipfile:
        raise TaskError('Bad JAR file, maybe empty: %s' % jar_path)
      for root, dirs, files in os.walk(tmpdir):
        for f in files:
          path = os.path.join(root, f)
          relpath = os.path.relpath(path, tmpdir).decode('utf-8')
          if Manifest.PATH != relpath:
            jar_file.write(path, relpath)

  def _mapped_dependencies(self, jardepmap, binary, confs):
    # TODO(John Sirois): rework product mapping towards well known types

    # Generate a map of jars for each unique artifact (org, name)
    externaljars = OrderedDict()
    visited = set()
    for conf in confs:
      mapped = jardepmap.get((binary, conf))
      if mapped:
        for basedir, jars in mapped.items():
          for externaljar in jars:
            if (basedir, externaljar) not in visited:
              visited.add((basedir, externaljar))
              keys = jardepmap.keys_for(basedir, externaljar)
              for key in keys:
                if isinstance(key, tuple) and len(key) == 3:
                  org, name, configuration = key
                  classpath_entry = externaljars.get((org, name))
                  if not classpath_entry:
                    classpath_entry = {}
                    externaljars[(org, name)] = classpath_entry
                  classpath_entry[conf] = os.path.join(basedir, externaljar)
    return externaljars.values()

  def _unexcluded_dependencies(self, jardepmap, binary):
    # TODO(John Sirois): Kill this and move jar exclusion to use confs
    excludes = set()
    for exclude_key in ((e.org, e.name) if e.name else e.org for e in binary.deploy_excludes):
      exclude = jardepmap.get(exclude_key)
      if exclude:
        for basedir, jars in exclude.items():
          for jar in jars:
            excludes.add((basedir, jar))
    if excludes:
      self.context.log.debug('Calculated excludes:\n\t%s' % '\n\t'.join(str(e) for e in excludes))

    externaljars = OrderedSet()

    def add_jars(target):
      mapped = jardepmap.get(target)
      if mapped:
        for basedir, jars in mapped.items():
          for externaljar in jars:
            if (basedir, externaljar) not in excludes:
              externaljars.add((basedir, externaljar))
            else:
              self.context.log.debug('Excluding %s from binary' % externaljar)

    binary.walk(add_jars)
    return externaljars
