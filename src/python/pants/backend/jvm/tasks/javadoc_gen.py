# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.jvmdoc_gen import Jvmdoc, JvmdocGen
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.util.memo import memoized


class JavadocGen(JvmdocGen):
  @classmethod
  @memoized
  def jvmdoc(cls):
    return Jvmdoc(tool_name='javadoc', product_type='javadoc')

  @classmethod
  def subsystem_dependencies(cls):
    return super(JavadocGen, cls).subsystem_dependencies() + (DistributionLocator,)

  def execute(self):
    def is_java(target):
      return target.has_sources('.java')

    self.generate_doc(is_java, self.create_javadoc_command)

  def create_javadoc_command(self, classpath, gendir, *targets):
    sources = []
    for target in targets:
      sources.extend(target.sources_relative_to_buildroot())

    if not sources:
      return None

    # Without a JDK/tools.jar we have no javadoc tool and cannot proceed, so check/acquire early.
    jdk = DistributionLocator.cached(jdk=True)
    tool_classpath = jdk.find_libs(['tools.jar'])

    args = ['-quiet',
            '-encoding', 'UTF-8',
            '-notimestamp',
            '-use',
            '-classpath', ':'.join(classpath),
            '-d', gendir]

    # Always provide external linking for java API
    offlinelinks = {'http://download.oracle.com/javase/6/docs/api/'}

    def link(target):
      for jar in target.jar_dependencies:
        if jar.apidocs:
          offlinelinks.add(jar.apidocs)
    for target in targets:
      target.walk(link, lambda t: t.is_jvm)

    for link in offlinelinks:
      args.extend(['-linkoffline', link, link])

    args.extend(self.args)

    args.extend(sources)

    java_executor = SubprocessExecutor(jdk)
    runner = java_executor.runner(jvm_options=self.jvm_options,
                                  classpath=tool_classpath,
                                  main='com.sun.tools.javadoc.Main',
                                  args=args)
    return runner.command
