# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import errno
import os

from twitter.common.dirutil import safe_mkdir

from pants.backend.codegen.targets.java_antlr_library import JavaAntlrLibrary
from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.targets.jaxb_library import JaxbLibrary
from pants.backend.codegen.targets.python_antlr_library import PythonAntlrLibrary
from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.targets.doc import Page
from pants.backend.core.targets.resources import Resources
from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.java_tests import JavaTests
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.targets.scala_tests import ScalaTests
from pants.backend.jvm.tasks.bootstrap_jvm_tools import BootstrapJvmTools
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants_test.base_test import BaseTest


class JvmToolTaskTestBase(BaseTest):
  """Prepares an ephemeral test build root that supports tasks that use jvm tool bootstrapping."""

  @property
  def alias_groups(self):
    return {
      'target_aliases': {
        'annotation_processor': AnnotationProcessor,
        'jar_library': JarLibrary,
        'java_antlr_library': JavaAntlrLibrary,
        'java_library': JavaLibrary,
        'java_protobuf_library': JavaProtobufLibrary,
        'java_thrift_library': JavaThriftLibrary,
        'jaxb_library': JaxbLibrary,
        'junit_tests': JavaTests,
        'jvm_binary': JvmBinary,
        'page': Page,
        'python_antlr_library': PythonAntlrLibrary,
        'python_binary': PythonBinary,
        'python_library': PythonLibrary,
        'python_test_suite': Dependencies,
        'python_tests': PythonTests,
        'python_thrift_library': PythonThriftLibrary,
        'resources': Resources,
        'scala_library': ScalaLibrary,
        'scala_specs': ScalaTests,
      },
      'exposed_objects': {
        'pants': lambda x: x,
        'jar': JarDependency,
      }
    }

  def setUp(self):
    real_config = self.config()

    super(JvmToolTaskTestBase, self).setUp()

    def link(path, optional=False, force=False):
      src = os.path.join(self.real_build_root, path)
      if not optional or os.path.exists(src):
        dest = os.path.join(self.build_root, path)
        safe_mkdir(os.path.dirname(dest))
        try:
          os.link(src, dest)
        except OSError as e:
          if force and e.errno == errno.EEXIST:
            os.unlink(dest)
            os.link(src, dest)
          else:
            raise e
        return dest

    def link_tree(path, optional=False, force=False):
      src = os.path.join(self.real_build_root, path)
      if not optional or os.path.exists(src):
        for abspath, dirs, files in os.walk(src):
          for f in files:
            link(os.path.relpath(os.path.join(abspath, f), self.real_build_root), force=force)

    # TODO(John Sirois): Find a way to do this cleanly
    link('pants.ini', force=True)

    # TODO(pl): Note that this pulls in a big chunk of the hairball to every test that
    # depends on it, because BUILD contains source_roots that specify a variety of types
    # from different backends.
    link('BUILD', force=True)

    link('BUILD.tools', force=True)
    support_dir = real_config.getdefault('pants_supportdir')
    link_tree(os.path.relpath(os.path.join(support_dir, 'ivy'), self.real_build_root), force=True)

  def prepare_execute(self, context, workdir, task_type):
    """Prepares a jvm tool using task for execution, ensuring any required jvm tools are
    bootstrapped.

    NB: Other task pre-requisites will not be ensured and tests must instead setup their own product
    requirements if any.

    :returns: The prepared Task
    """
    # TODO(John Sirois): This is emulating Engine behavior - construct reverse order, then execute;
    # instead it should probably just be using an Engine.
    task = task_type(context, workdir)
    BootstrapJvmTools(context, workdir).execute()
    return task

  def execute(self, context, workdir, task_type):
    """Executes the given task ensuring any required jvm tools are bootstrapped.

    NB: Other task pre-requisites will not be ensured and tests must instead setup their own product
    requirements if any.
    """
    # TODO(John Sirois): This is emulating Engine behavior - construct reverse order, then execute;
    # instead it should probably just be using an Engine.
    task = self.prepare_execute(context, workdir, task_type)
    task.execute()
