# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)
from contextlib import contextmanager

import os

from twitter.common.collections.ordereddict import OrderedDict
from twitter.common.collections.orderedset import OrderedSet

from pants.backend.jvm.tasks.jar_task import JarTask
from pants.backend.jvm.targets.jvm_binary import JvmBinary


class JvmBinaryTask(JarTask):

  @staticmethod
  def is_binary(target):
    return isinstance(target, JvmBinary)

  @staticmethod
  def add_main_manifest_entry(jar, binary):
    """Creates a jar manifest for the given binary.

    If the binary declares a main then a 'Main-Class' manifest entry will be included.
    """
    main = binary.main or '*** java -jar not supported, please use -cp and pick a main ***'
    jar.main(main)

  def __init__(self, *args, **kwargs):
    super(JvmBinaryTask, self).__init__(*args, **kwargs)
    self._jar_builder = self.prepare_jar_builder()

  def prepare(self, round_manager):
     super(JvmBinaryTask, self).prepare(round_manager)
     round_manager.require('jar_dependencies', predicate=self.is_binary)

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

    with self.context.new_workunit(name='create-monolithic-jar'):
      with self.open_jar(path,
                         jar_rules=binary.deploy_jar_rules,
                         overwrite=True,
                         compressed=True) as jar:

        with self.context.new_workunit(name='add-internal-classes'):
          self._jar_builder.add_target(jar, binary, recursive=True)

        if with_external_deps:
          with self.context.new_workunit(name='add-dependency-jars'):
            for basedir, external_jar in self.list_external_jar_dependencies(binary):
              external_jar_path = os.path.join(basedir, external_jar)
              self.context.log.debug('  dumping %s' % external_jar_path)
              jar.writejar(external_jar_path)

        yield jar

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
