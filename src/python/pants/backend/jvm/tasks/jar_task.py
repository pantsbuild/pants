# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod
from contextlib import contextmanager
import os
import tempfile

from twitter.common.collections import maybe_list
from twitter.common.contextutil import temporary_dir
from twitter.common.lang import AbstractClass, Compatibility

from pants.backend.jvm.targets.jvm_binary import Duplicate, Skip, JarRules
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.java.jar.manifest import Manifest


class Jar(object):
  """Encapsulates operations to build up or update a jar file.

  Upon construction the jar is conceptually opened for writes.  The write methods are called to
  add to the jar's contents and then changes are finalized with a call to close.  If close is not
  called the staged changes will be lost.
  """

  class Error(Exception):
    """Indicates an error creating or updating a jar on disk."""

  class Entry(AbstractClass):
    """An entry to be written to a jar."""

    def __init__(self, dest):
      self._dest = dest

    @property
    def dest(self):
      """The destination path of the entry in the jar."""
      return self._dest

    @abstractmethod
    def materialize(self, scratch_dir):
      """Materialize this entry's source data into a filesystem path.

      :param string scratch_dir:  A temporary directory that may be used to do any work required
        to materialize the entry as a source file. The caller is responsible for cleaning up
        `scratch_dir` after the jar is closed.
      :returns: The path to the source data.
      """

  class FileSystemEntry(Entry):
    """An entry backed by an existing file on disk."""

    def __init__(self, src, dest=None):
      super(Jar.FileSystemEntry, self).__init__(dest)
      self._src = src

    def materialize(self, _):
      return self._src

  class MemoryEntry(Entry):
    """An entry backed by an in-memory sequence of bytes."""

    def __init__(self, dest, contents):
      super(Jar.MemoryEntry, self).__init__(dest)
      self._contents = contents

    def materialize(self, scratch_dir):
      fd, path = tempfile.mkstemp(dir=scratch_dir)
      try:
        os.write(fd, self._contents)
      finally:
        os.close(fd)
      return path

  def __init__(self):
    self._entries = []
    self._jars = []
    self._manifest = None
    self._main = None
    self._classpath = None

  def main(self, main):
    """Specifies a Main-Class entry for this jar's manifest.

    :param string main: a fully qualified class name
    """
    if not main or not isinstance(main, Compatibility.string):
      raise ValueError('The main entry must be a non-empty string')
    self._main = main

  def classpath(self, classpath):
    """Specifies a Class-Path entry for this jar's manifest.

    :param list classpath: a list of paths
    """
    self._classpath = maybe_list(classpath)

  def write(self, src, dest=None):
    """Schedules a write of the file at ``src`` to the ``dest`` path in this jar.

    If the ``src`` is a file, then ``dest`` must be specified.

    If the ``src`` is a directory then by default all descendant files will be added to the jar as
    entries carrying their relative path.  If ``dest`` is specified it will be prefixed to each
    descendant's relative path to form its jar entry path.

    :param string src: the path to the pre-existing source file or directory
    :param string dest: the path the source file or directory should have in this jar
    """
    if not src or not isinstance(src, Compatibility.string):
      raise ValueError('The src path must be a non-empty string, got %s of type %s.'
                       % (src, type(src)))
    if dest and not isinstance(dest, Compatibility.string):
      raise ValueError('The dest entry path must be a non-empty string, got %s of type %s.'
                       % (dest, type(dest)))
    if not os.path.isdir(src) and not dest:
      raise self.Error('Source file %s must have a jar destination specified' % src)

    self._add_entry(self.FileSystemEntry(src, dest))

  def writestr(self, path, contents):
    """Schedules a write of the file ``contents`` to the given ``path`` in this jar.

    :param string path: the path to write the contents to in this jar
    :param string contents: the raw byte contents of the file to write to ``path``
    """
    if not path or not isinstance(path, Compatibility.string):
      raise ValueError('The path must be a non-empty string')

    if contents is None or not isinstance(contents, Compatibility.bytes):
      raise ValueError('The contents must be a sequence of bytes')

    self._add_entry(self.MemoryEntry(path, contents))

  def _add_entry(self, entry):
    if Manifest.PATH == entry.dest:
      self._manifest = entry
    else:
      self._entries.append(entry)

  def writejar(self, jar):
    """Schedules all entries from the given ``jar``'s to be added to this jar save for the manifest.

    :param string jar: the path to the pre-existing jar to graft into this jar
    """
    if not jar or not isinstance(jar, Compatibility.string):
      raise ValueError('The jar path must be a non-empty string')

    self._jars.append(jar)

  @contextmanager
  def _render_jar_tool_args(self):
    args = []

    if self._main:
      args.append('-main=%s' % self._main)

    if self._classpath:
      args.append('-classpath=%s' % ','.join(self._classpath))

    with temporary_dir() as stage_dir:
      if self._manifest:
        args.append('-manifest=%s' % self._manifest.materialize(stage_dir))

      if self._entries:
        def as_cli_entry(entry):
          src = entry.materialize(stage_dir)
          return '%s=%s' % (src, entry.dest) if entry.dest else src

        args.append('-files=%s' % ','.join(map(as_cli_entry, self._entries)))

      if self._jars:
        args.append('-jars=%s' % ','.join(self._jars))

      yield args


class JarTask(NailgunTask):
  """A baseclass for tasks that need to create or update jars.

  All subclasses will share the same underlying nailgunned jar tool and thus benefit from fast
  invocations.
  """

  @staticmethod
  def _flag(bool_value):
    return 'true' if bool_value else 'false'

  _DUPLICATE_ACTION_TO_NAME = {
      Duplicate.SKIP: 'SKIP',
      Duplicate.REPLACE: 'REPLACE',
      Duplicate.CONCAT: 'CONCAT',
      Duplicate.FAIL: 'THROW',
  }

  @classmethod
  def _action_name(cls, action):
    name = cls._DUPLICATE_ACTION_TO_NAME.get(action)
    if name is None:
      raise ValueError('Unrecognized duplicate action: %s' % action)
    return name

  _JAR_TOOL_CLASSPATH_KEY = 'jar_tool'

  def __init__(self, context, workdir):
    super(JarTask, self).__init__(context, workdir=workdir, jdk=True, nailgun_name='jar-tool')

    # TODO(John Sirois): Consider poking a hole for custom jar-tool jvm args - namely for Xmx
    # control.

    jar_bootstrap_tools = context.config.getlist('jar-tool', 'bootstrap-tools', [':jar-tool'])
    self.register_jvm_tool(self._JAR_TOOL_CLASSPATH_KEY, jar_bootstrap_tools)

  @contextmanager
  def open_jar(self, path, overwrite=False, compressed=True, jar_rules=None):
    """Yields a :class:`twitter.pants.jvm.jar_task.Jar` that will be written when the context exits.

    :param string path: the path to the jar file
    :param bool overwrite: overwrite the file at ``path`` if it exists; ``False`` by default; ie:
      update the pre-existing jar at ``path``
    :param bool compressed: entries added to the jar should be compressed; ``True`` by default
    :param jar_rules: an optional set of rules for handling jar exclusions and duplicates
    """
    jar = Jar()
    try:
      yield jar
    except jar.Error as e:
      raise TaskError('Failed to write to jar at %s: %s' % (path, e))

    with jar._render_jar_tool_args() as args:
      args.append('-update=%s' % self._flag(not overwrite))
      args.append('-compress=%s' % self._flag(compressed))

      jar_rules = jar_rules or JarRules.default()
      args.append('-default_action=%s' % self._action_name(jar_rules.default_dup_action))

      skip_patterns = []
      duplicate_actions = []

      for rule in jar_rules.rules:
        if isinstance(rule, Skip):
          skip_patterns.append(rule.apply_pattern)
        elif isinstance(rule, Duplicate):
          duplicate_actions.append('%s=%s' % (rule.apply_pattern.pattern,
                                              self._action_name(rule.action)))
        else:
          raise ValueError('Unrecognized rule: %s' % rule)

      if skip_patterns:
        args.append('-skip=%s' % ','.join(p.pattern for p in skip_patterns))

      if duplicate_actions:
        args.append('-policies=%s' % ','.join(duplicate_actions))

      args.append(path)

      jvm_args = self.context.config.getlist('jar-tool', 'jvm_args', default=['-Xmx64M'])
      self.runjava(self.tool_classpath(self._JAR_TOOL_CLASSPATH_KEY),
                   'com.twitter.common.jar.tool.Main',
                   jvm_options=jvm_args,
                   args=args,
                   workunit_name='jar-tool',
                   workunit_labels=[WorkUnit.TOOL, WorkUnit.JVM, WorkUnit.NAILGUN])
