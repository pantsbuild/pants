# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.backend.jvm.tasks.unpack_jars import UnpackJars
from pants.base.exceptions import TaskError
from twitter.common.collections import OrderedSet

from pants.contrib.android.targets.android_binary import AndroidBinary
from pants.contrib.android.tasks.android_task import AndroidTask


class DxCompile(AndroidTask, NailgunTask):
  """Compile java classes into dex files, Dalvik executables, for AndroidBinary targets.

  Gather the class files of the AndroidBinary and all of its dependencies. This includes the
  AndroidLibrary targets that the AndroidBinary depends on. AndroidLibrary artifacts (.jars and
  .aars) were unpacked during the UnpackLibraries task. The DxCompile task will gather all
  those classes and compile them into a dex file. When gathering the classes, the DxCompile
  task will filter unpacked AndroidLibraries in order to honor any include/exclude patterns.

  This task will silently skip any duplicate class files but will raise a
  DuplicateClassFileException if it detects a version conflict in any AndroidLibrary artifacts.
  """

  class DuplicateClassFileException(TaskError):
    """Raise is raised when multiple copies of the same class are being added to dex file."""

  class EmptyDexError(TaskError):
    """Raise when no classes are found to be packed into the dex file."""

  # Name of output file. "Output name must end with one of: .dex .jar .zip .apk or be a directory."
  DEX_NAME = 'classes.dex'

  @staticmethod
  def is_android_binary(target):
    """Return True if target has class files to be compiled into dex."""
    return isinstance(target, AndroidBinary)

  @classmethod
  def register_options(cls, register):
    super(DxCompile, cls).register_options(register)
    register('--build-tools-version',
             help='Create the dex file using this version of the Android build tools.')

  @classmethod
  def product_types(cls):
    return ['dex']

  @classmethod
  def prepare(cls, options, round_manager):
    super(DxCompile, cls).prepare(options, round_manager)
    round_manager.require_data('runtime_classpath')
    round_manager.require_data('unpacked_libraries')

  def __init__(self, *args, **kwargs):
    super(DxCompile, self).__init__(*args, **kwargs)
    self._forced_build_tools = self.get_options().build_tools_version
    self._forced_jvm_options = self.get_options().jvm_options

  @property
  def cache_target_dirs(self):
    return True

  def _render_args(self, outdir, entries):
    dex_file = os.path.join(outdir, self.DEX_NAME)
    args = []
    # Glossary of dx.jar flags.
    #   : '--dex' to create a Dalvik executable.
    #   : '--no-strict' allows the dx.jar to skip verifying the package path. This allows us to
    #            pass a list of classes as opposed to a top-level dir.
    #   : '--output' tells the dx.jar where to put and what to name the created file.
    #            See comment on self.classes_dex for restrictions.
    args.extend(['--dex', '--no-strict', '--output={0}'.format(dex_file)])
    args.extend(entries)
    return args

  def _compile_dex(self, args, build_tools_version):
    classpath = [self.dx_jar_tool(build_tools_version)]

    # TODO(mateor) Declare a subsystem_dependencies on JVM and use that to get options.
    jvm_options = self._forced_jvm_options if self._forced_jvm_options else None
    java_main = 'com.android.dx.command.Main'
    return self.runjava(classpath=classpath, jvm_options=jvm_options, main=java_main,
                        args=args, workunit_name='dx')

  def _filter_unpacked_dir(self, target, unpacked_dir, class_files):
    # The Dx tool returns failure if more than one copy of a class is packed into the dex file and
    # it is easy to fetch duplicate libraries (as well as conflicting versions) from the SDK repos.
    # This filters the contents of the unpacked_dir against the include/exclude patterns of the
    # target, then compares the filtered files against previously gathered class_files to
    # dedupe and detect version conflicts.

    file_filter = UnpackJars.get_unpack_filter(target)
    for root, _, file_names in os.walk(unpacked_dir):
      for filename in file_names:
        # Calculate the filename relative to the unpacked_dir and then filter.
        relative_dir = os.path.relpath(root, unpacked_dir)
        class_file = os.path.join(relative_dir, filename)
        if file_filter(class_file):
          class_location = os.path.join(root, filename)

          # If the class_file (e.g. 'a/b/c/Hello.class') has already been added, then compare the
          # full path. If the full path is identical then we can ignore it as a duplicate. If
          # the path is different, that means that there is probably conflicting version
          # numbers amongst the library deps and so we raise an exception.
          if class_file in class_files:
            if class_files[class_file] != class_location:
              raise TaskError("Dependency:\n{}\n\nConflicts\n1: {} "
                              "\n2: {}".format(target, class_location, class_files[class_file]))
          class_files[class_file] = class_location
    return class_files.values()

  def _gather_dex_entries(self, target):
    """Gather relevant dex inputs from a walk of AndroidBinary's dependency graph.

    The dx tool accepts 1) directories, 2) jars/zips, or 3) loose classfiles. The return value
    will contain any or all of those.
    """
    classpath_products = self.context.products.get_data('runtime_classpath')
    unpacked_archives = self.context.products.get('unpacked_libraries')

    gathered_entries = OrderedSet()
    class_files = {}

    def get_entries(tgt):
      # We gather just internal classpath elements here.  Unpacked external dependency classpath
      # elements are gathered just below.
      cp_entries = ClasspathUtil.internal_classpath((tgt,), classpath_products)
      gathered_entries.update(cp_entries)

      # Gather classes from the contents of unpacked libraries.
      unpacked = unpacked_archives.get(tgt)
      if unpacked:
        # If there are unpacked_archives then we know this target is an AndroidLibrary.
        for archives in unpacked.values():
          for unpacked_dir in archives:
            try:
              gathered_entries.update(self._filter_unpacked_dir(tgt, unpacked_dir, class_files))
            except TaskError as e:
              raise self.DuplicateClassFileException(
                  "Attempted to add duplicate class files from separate libraries into dex file! "
                  "This likely indicates a version conflict in the target's dependencies.\n"
                  "\nTarget:\n{}\n{}".format(target, e))

    target.walk(get_entries)
    return gathered_entries

  def execute(self):
    targets = self.context.targets(self.is_android_binary)

    with self.invalidated(targets) as invalidation_check:
      for vt in invalidation_check.all_vts:
        if not vt.valid:
          entries = self._gather_dex_entries(vt.target)
          if not entries:
            raise self.EmptyDexError("No classes were found for {}.".format(vt.target))

          args = self._render_args(vt.results_dir, entries)
          self._compile_dex(args, vt.target.build_tools_version)
        self.context.products.get('dex').add(vt.target, vt.results_dir).append(self.DEX_NAME)

  def dx_jar_tool(self, build_tools_version):
    """Return the appropriate dx.jar.

    :param string build_tools_version: The Android build-tools version number (e.g. '19.1.0').
    """
    build_tools = self._forced_build_tools if self._forced_build_tools else build_tools_version
    dx_jar = os.path.join('build-tools', build_tools, 'lib', 'dx.jar')
    return self.android_sdk.register_android_tool(dx_jar)
