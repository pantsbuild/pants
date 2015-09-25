# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import tempfile
from abc import abstractmethod
from contextlib import contextmanager

import six
from six import binary_type, string_types
from twitter.common.collections import maybe_list

from pants.backend.jvm.subsystems.jar_tool import JarTool
from pants.backend.jvm.targets.java_agent import JavaAgent
from pants.backend.jvm.targets.jvm_binary import Duplicate, JarRules, JvmBinary, Skip
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.binaries.binary_util import safe_args
from pants.java.jar.manifest import Manifest
from pants.util.contextutil import temporary_dir
from pants.util.meta import AbstractClass


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
    self._manifest_entry = None
    self._main = None
    self._classpath = None

  def main(self, main):
    """Specifies a Main-Class entry for this jar's manifest.

    :param string main: a fully qualified class name
    """
    if not main or not isinstance(main, string_types):
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
    if not src or not isinstance(src, string_types):
      raise ValueError('The src path must be a non-empty string, got {} of type {}.'.format(
        src, type(src)))
    if dest and not isinstance(dest, string_types):
      raise ValueError('The dest entry path must be a non-empty string, got {} of type {}.'.format(
        dest, type(dest)))
    if not os.path.isdir(src) and not dest:
      raise self.Error('Source file {} must have a jar destination specified'.format(src))

    self._add_entry(self.FileSystemEntry(src, dest))

  def writestr(self, path, contents):
    """Schedules a write of the file ``contents`` to the given ``path`` in this jar.

    :param string path: the path to write the contents to in this jar
    :param string contents: the raw byte contents of the file to write to ``path``
    """
    if not path or not isinstance(path, string_types):
      raise ValueError('The path must be a non-empty string')

    if contents is None or not isinstance(contents, binary_type):
      raise ValueError('The contents must be a sequence of bytes')

    self._add_entry(self.MemoryEntry(path, contents))

  def _add_entry(self, entry):
    if Manifest.PATH == entry.dest:
      self._manifest_entry = entry
    else:
      self._entries.append(entry)

  def writejar(self, jar):
    """Schedules all entries from the given ``jar``'s to be added to this jar save for the manifest.

    :param string jar: the path to the pre-existing jar to graft into this jar
    """
    if not jar or not isinstance(jar, string_types):
      raise ValueError('The jar path must be a non-empty string')

    self._jars.append(jar)

  @contextmanager
  def _render_jar_tool_args(self, options):
    """Format the arguments to jar-tool.

    :param Options options:
    """
    args = []

    with temporary_dir() as manifest_stage_dir:
      classpath = self._classpath or []

      def as_cli_entry(entry):
        src = entry.materialize(manifest_stage_dir)
        return '{}={}'.format(src, entry.dest) if entry.dest else src
      files = map(as_cli_entry, self._entries) if self._entries else []

      jars = self._jars or []

      with safe_args(classpath, options, delimiter=',') as classpath_args:
        with safe_args(files, options, delimiter=',') as files_args:
          with safe_args(jars, options, delimiter=',') as jars_args:

            # If you specify --manifest to jar-tool you cannot specify --main.
            if self._manifest_entry:
              manifest_file = self._manifest_entry.materialize(manifest_stage_dir)
            else:
              manifest_file = None

            if self._main and manifest_file:
              main_arg = None
              with open(manifest_file, 'a') as f:
                f.write("Main-Class: {}\n".format(self._main))
            else:
              main_arg = self._main

            if main_arg:
              args.append('-main={}'.format(self._main))

            if classpath_args:
              args.append('-classpath={}'.format(','.join(classpath_args)))

            if manifest_file:
              args.append('-manifest={}'.format(manifest_file))

            if files_args:
              args.append('-files={}'.format(','.join(files_args)))

            if jars_args:
              args.append('-jars={}'.format(','.join(jars_args)))

            yield args


class JarTask(NailgunTask):
  """A baseclass for tasks that need to create or update jars.

  All subclasses will share the same underlying nailgunned jar tool and thus benefit from fast
  invocations.
  """

  @classmethod
  def global_subsystems(cls):
    return super(JarTask, cls).global_subsystems() + (JarTool,)

  @classmethod
  def prepare(cls, options, round_manager):
    super(JarTask, cls).prepare(options, round_manager)
    JarTool.prepare_tools(round_manager)

  @staticmethod
  def _flag(bool_value):
    return 'true' if bool_value else 'false'

  _DUPLICATE_ACTION_TO_NAME = {
      Duplicate.SKIP: 'SKIP',
      Duplicate.REPLACE: 'REPLACE',
      Duplicate.CONCAT: 'CONCAT',
      Duplicate.CONCAT_TEXT: 'CONCAT_TEXT',
      Duplicate.FAIL: 'THROW',
  }

  @classmethod
  def _action_name(cls, action):
    name = cls._DUPLICATE_ACTION_TO_NAME.get(action)
    if name is None:
      raise ValueError('Unrecognized duplicate action: {}'.format(action))
    return name

  def __init__(self, *args, **kwargs):
    super(JarTask, self).__init__(*args, **kwargs)
    self.set_distribution(jdk=True)
    # TODO(John Sirois): Consider poking a hole for custom jar-tool jvm args - namely for Xmx
    # control.

  @contextmanager
  def open_jar(self, path, overwrite=False, compressed=True, jar_rules=None):
    """Yields a Jar that will be written when the context exits.

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
      raise TaskError('Failed to write to jar at {}: {}'.format(path, e))

    with jar._render_jar_tool_args(self.get_options()) as args:
      if args:  # Don't build an empty jar
        args.append('-update={}'.format(self._flag(not overwrite)))
        args.append('-compress={}'.format(self._flag(compressed)))

        jar_rules = jar_rules or JarRules.default()
        args.append('-default_action={}'.format(self._action_name(jar_rules.default_dup_action)))

        skip_patterns = []
        duplicate_actions = []

        for rule in jar_rules.rules:
          if isinstance(rule, Skip):
            skip_patterns.append(rule.apply_pattern)
          elif isinstance(rule, Duplicate):
            duplicate_actions.append('{}={}'.format(
              rule.apply_pattern.pattern, self._action_name(rule.action)))
          else:
            raise ValueError('Unrecognized rule: {}'.format(rule))

        if skip_patterns:
          args.append('-skip={}'.format(','.join(p.pattern for p in skip_patterns)))

        if duplicate_actions:
          args.append('-policies={}'.format(','.join(duplicate_actions)))

        args.append(path)

        if JarTool.global_instance().run(context=self.context, runjava=self.runjava, args=args):
          raise TaskError('jar-tool failed')


class JarBuilderTask(JarTask):

  class JarBuilder(AbstractClass):
    """A utility to aid in adding the classes and resources associated with targets to a jar."""

    @staticmethod
    def _add_agent_manifest(agent, manifest):
      # TODO(John Sirois): refactor an agent model to support 'Boot-Class-Path' properly.
      manifest.addentry(Manifest.MANIFEST_VERSION, '1.0')
      if agent.premain:
        manifest.addentry('Premain-Class', agent.premain)
      if agent.agent_class:
        manifest.addentry('Agent-Class', agent.agent_class)
      if agent.can_redefine:
        manifest.addentry('Can-Redefine-Classes', 'true')
      if agent.can_retransform:
        manifest.addentry('Can-Retransform-Classes', 'true')
      if agent.can_set_native_method_prefix:
        manifest.addentry('Can-Set-Native-Method-Prefix', 'true')

    @staticmethod
    def _add_manifest_entries(jvm_binary_target, manifest):
      """Add additional fields to MANIFEST.MF as declared in the ManifestEntries structure.

      :param JvmBinary jvm_binary_target:
      :param Manifest manifest:
      """
      for header, value in six.iteritems(jvm_binary_target.manifest_entries.entries):
        manifest.addentry(header, value)

    @staticmethod
    def prepare(round_manager):
      """Prepares the products needed to use `create_jar_builder`.

      This method should be called during task preparation to ensure the classes and resources
      needed for jarring targets are mapped by upstream tasks that generate these.

      Later, in execute context, the `create_jar_builder` method can be called to get back a
      prepared ``JarTask.JarBuilder`` ready for use.
      """
      round_manager.require_data('resources_by_target')
      round_manager.require_data('classes_by_target')

    def __init__(self, context, jar):
      self._context = context
      self._jar = jar
      self._manifest = Manifest()

    def add_target(self, target, recursive=False):
      """Adds the classes and resources for a target to an open jar.

      :param target: The target to add generated classes and resources for.
      :param bool recursive: `True` to add classes and resources for the target's transitive
        internal dependency closure.
      :returns: The list of targets that actually contributed classes or resources or both to the
        jar.
      """
      classes_by_target = self._context.products.get_data('classes_by_target')
      resources_by_target = self._context.products.get_data('resources_by_target')

      targets_added = []

      def add_to_jar(tgt):
        target_classes = classes_by_target.get(tgt)

        target_resources = []

        # TODO(pl): https://github.com/pantsbuild/pants/issues/206
        resource_products_on_target = resources_by_target.get(tgt)
        if resource_products_on_target:
          target_resources.append(resource_products_on_target)

        if tgt.has_resources:
          target_resources.extend(resources_by_target.get(r) for r in tgt.resources)

        if target_classes or target_resources:
          targets_added.append(tgt)

          def add_products(target_products):
            if target_products:
              for root, products in target_products.rel_paths():
                for prod in products:
                  self._jar.write(os.path.join(root, prod), prod)

          add_products(target_classes)
          for resources_target in target_resources:
            add_products(resources_target)

          if isinstance(tgt, JavaAgent):
            self._add_agent_manifest(tgt, self._manifest)

      if isinstance(target, JvmBinary):
        self._add_manifest_entries(target, self._manifest)

      if recursive:
        target.walk(add_to_jar)
      else:
        add_to_jar(target)

      return targets_added

    def commit_manifest(self, jar):
      """Updates the manifest in the jar being written to.

      Typically done right before closing the .jar. This gives a chance for all targets to bundle
      in their contributions to the manifest.
      """
      if not self._manifest.is_empty():
        jar.writestr(Manifest.PATH, self._manifest.contents())

  @classmethod
  def prepare(cls, options, round_manager):
    super(JarBuilderTask, cls).prepare(options, round_manager)
    cls.JarBuilder.prepare(round_manager)

  @contextmanager
  def create_jar_builder(self, jar):
    """Creates a ``JarTask.JarBuilder`` ready for use.

    This method should be called during in `execute` context and only after ensuring
    `JarTask.JarBuilder.prepare` has already been called in `prepare` context.

    :param jar: An opened ``pants.backend.jvm.tasks.jar_task.Jar`.
    """
    builder = self.JarBuilder(self.context, jar)
    yield builder
    builder.commit_manifest(jar)
