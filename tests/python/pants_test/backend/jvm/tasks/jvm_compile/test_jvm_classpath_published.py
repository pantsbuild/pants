# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
from textwrap import dedent

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.classpath_entry import ArtifactClasspathEntry
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_compile.jvm_classpath_publisher import RuntimeClasspathPublisher
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.java.jar.jar_dependency import JarDependency
from pants.java.jar.jar_dependency_utils import M2Coordinate
from pants.testutil.task_test_base import TaskTestBase
from pants.util.contextutil import open_zip, temporary_dir
from pants.util.dirutil import safe_open, touch


class RuntimeClasspathPublisherTest(TaskTestBase):
  DEFAULT_CONF = 'default'

  @classmethod
  def task_type(cls):
    return RuntimeClasspathPublisher

  @classmethod
  def alias_groups(cls):
    return BuildFileAliases(
      targets={
        'java_library': JavaLibrary,
        'jar_library': JarLibrary,
      },
      objects={
        'jar': JarDependency,
      }
    )

  # TODO (peiyu) This overlaps with test cases in `ClasspathUtilTest`. Clean this up once we
  # fully switch to `target.id` based canonical classpath.
  def test_incremental_caching(self):
    with temporary_dir(root_dir=self.pants_workdir) as jar_dir, \
         temporary_dir(root_dir=self.pants_workdir) as dist_dir:
      self.set_options(pants_distdir=dist_dir)

      target = self.make_target(
        'java/classpath:java_lib',
        target_type=JavaLibrary,
        sources=['com/foo/Bar.java'],
      )
      context = self.context(target_roots=[target])
      runtime_classpath = context.products.get_data('runtime_classpath',
                                                    init_func=ClasspathProducts.init_func(self.pants_workdir))
      task = self.create_task(context)

      target_classpath_output = os.path.join(dist_dir, self.options_scope)

      # Create a classpath entry.
      touch(os.path.join(jar_dir, 'z1.jar'))
      runtime_classpath.add_for_target(target, [(self.DEFAULT_CONF, os.path.join(jar_dir, 'z1.jar'))])
      task.execute()
      # Check only one symlink and classpath.txt were created.
      self.assertEqual(len(os.listdir(target_classpath_output)), 2)
      self.assertEqual(
        os.path.realpath(os.path.join(target_classpath_output,
                                      sorted(os.listdir(target_classpath_output))[0])),
        os.path.join(jar_dir, 'z1.jar')
      )

      # Remove the classpath entry.
      runtime_classpath.remove_for_target(target, [(self.DEFAULT_CONF, os.path.join(jar_dir, 'z1.jar'))])

      # Add a different classpath entry
      touch(os.path.join(jar_dir, 'z2.jar'))
      runtime_classpath.add_for_target(target, [(self.DEFAULT_CONF, os.path.join(jar_dir, 'z2.jar'))])
      task.execute()
      # Check the symlink was updated.
      self.assertEqual(len(os.listdir(target_classpath_output)), 2)
      self.assertEqual(
        os.path.realpath(os.path.join(target_classpath_output,
                                      sorted(os.listdir(target_classpath_output))[0])),
        os.path.join(jar_dir, 'z2.jar')
      )

      # Add a different classpath entry
      touch(os.path.join(jar_dir, 'z3.jar'))
      runtime_classpath.add_for_target(target, [(self.DEFAULT_CONF, os.path.join(jar_dir, 'z3.jar'))])
      task.execute()
      self.assertEqual(len(os.listdir(target_classpath_output)), 3)

      classpath = sorted(os.listdir(target_classpath_output))[2]
      with safe_open(os.path.join(target_classpath_output, classpath)) as classpath_file:
        # Assert there is only one line ending with a newline
        self.assertListEqual(
          classpath_file.readlines(),
          [
            os.pathsep.join([os.path.join(jar_dir, 'z2.jar'), os.path.join(jar_dir, 'z3.jar')]) + '\n'
          ]
        )

  def _assert_internal_classpath_option(self, *, manifest_jar: bool, internal_classpath_only: bool) -> None:
    with temporary_dir(root_dir=self.pants_workdir) as jar_dir, \
         temporary_dir(root_dir=self.pants_workdir) as dist_dir:
      self.set_options(pants_distdir=dist_dir,
                       internal_classpath_only=internal_classpath_only,
                       manifest_jar=manifest_jar)

      self.add_to_build_file('java/classpath', dedent("""\
      jar_library(
        name='jar-lib',
        jars=[
          jar(org='commons-io', name='commons-io', rev='2.6'),
        ],
      )

      java_library(
        name='java-lib',
        sources=['com/foo/Bar.java'],
        dependencies=[
          ':jar-lib',
        ],
      )
      """))
      jar_lib = self.target('java/classpath:jar-lib')
      init_target = self.target('java/classpath:java-lib')
      context = self.context(target_roots=[jar_lib, init_target])
      runtime_classpath = context.products.get_data('runtime_classpath',
                                                    init_func=ClasspathProducts.init_func(self.pants_workdir))
      task = self.create_task(context)

      target_classpath_output = os.path.join(dist_dir, self.options_scope)

      # Create a classpath entry.
      touch(os.path.join(jar_dir, 'jar-lib-target.jar'))
      touch(os.path.join(jar_dir, 'java-lib-target.jar'))

      cache_path = os.path.join(jar_dir, 'jar-lib-target.jar')
      runtime_classpath.add_for_target(jar_lib, [(self.DEFAULT_CONF, ArtifactClasspathEntry(
        path=cache_path,
        coordinate=M2Coordinate(org='commons-io', name='commons-io', rev='2.6'),
        cache_path=cache_path,
      ))])
      runtime_classpath.add_for_target(init_target, [(self.DEFAULT_CONF, os.path.join(jar_dir, 'java-lib-target.jar'))])

      task.execute()

      if manifest_jar:
        if internal_classpath_only:
          expected_num_artifacts = 1
        else:
          expected_num_artifacts = 2
        manifest_jar_path = os.path.join(target_classpath_output, 'manifest.jar')
        with open_zip(manifest_jar_path) as zf:
          with zf.open('META-INF/MANIFEST.MF') as manifest_file:
            all_output = ''.join(
              re.sub(r'^(Class-Path:)? |\n+', '', line.decode('utf-8')) for line in manifest_file
            ).split(' ')
      else:
        if internal_classpath_only:
          expected_num_artifacts = 2
        else:
          expected_num_artifacts = 4
        all_output = os.listdir(target_classpath_output)

      # Check that the artifacts from the jar library are only exported with
      # --no-internal-classpath-only.
      self.assertEqual(len(all_output), expected_num_artifacts)

      self.assertTrue(any('java-lib' in jar for jar in all_output))
      if internal_classpath_only:
        self.assertFalse(any('jar-lib' in jar for jar in all_output))
      else:
        self.assertTrue(any('jar-lib' in jar for jar in all_output))

  def test_internal_classpath_only(self):
    self._assert_internal_classpath_option(manifest_jar=True, internal_classpath_only=True)
    self._assert_internal_classpath_option(manifest_jar=False, internal_classpath_only=True)

  def test_no_internal_classpath_only(self):
    self._assert_internal_classpath_option(manifest_jar=True, internal_classpath_only=False)
    self._assert_internal_classpath_option(manifest_jar=False, internal_classpath_only=False)
