# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.tasks.jvmdoc_gen import Jvmdoc, JvmdocGen


javadoc = Jvmdoc(tool_name='javadoc', product_type='javadoc')


def is_java(target):
  return target.has_sources('.java')


class JavadocGen(JvmdocGen):
  @classmethod
  def jvmdoc(cls):
    return javadoc

  def execute(self):
    self.generate_doc(is_java, create_javadoc_command)


def create_javadoc_command(classpath, gendir, *targets):
  sources = []
  for target in targets:
    sources.extend(target.sources_relative_to_buildroot())

  if not sources:
    return None

  # TODO(John Sirois): try com.sun.tools.javadoc.Main via ng
  command = [
    'javadoc',
    '-quiet',
    '-encoding', 'UTF-8',
    '-notimestamp',
    '-use',
    '-classpath', ':'.join(classpath),
    '-d', gendir,
  ]

  # Always provide external linking for java API
  offlinelinks = set(['http://download.oracle.com/javase/6/docs/api/'])

  def link(target):
    for jar in target.jar_dependencies:
      if jar.apidocs:
        offlinelinks.add(jar.apidocs)
  for target in targets:
    target.walk(link, lambda t: t.is_jvm)

  for link in offlinelinks:
    command.extend(['-linkoffline', link, link])

  command.extend(sources)
  return command
