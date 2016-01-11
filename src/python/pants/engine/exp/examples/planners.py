# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
from abc import abstractmethod, abstractproperty

from twitter.common.collections import OrderedSet

from pants.base.exceptions import TaskError
from pants.build_graph.address import Address
from pants.engine.exp.addressable import SubclassesOf, addressable_list
from pants.engine.exp.configuration import Struct, StructWithDeps
from pants.engine.exp.graph import Graph
from pants.engine.exp.mapper import AddressMapper
from pants.engine.exp.parsers import parse_json
from pants.engine.exp.scheduler import (LocalScheduler, SelectAddress, SelectDependencies,
                                        SelectSubject)
from pants.engine.exp.targets import Sources, Target
from pants.util.memo import memoized, memoized_property


def printing_func(func):
  @functools.wraps(func)
  def wrapper(**inputs):
    print('{} being executed with inputs: {}'.format(func.__name__, inputs))
    product = func(**inputs)
    return product if product else '<<<Fake{}Product>>>'.format(func.__name__)
  return wrapper


class JavaSources(Sources):
  extensions = ('.java',)


class ScalaSources(Sources):
  extensions = ('.scala',)


class PythonSources(Sources):
  extensions = ('.py',)


class ThriftSources(Sources):
  extensions = ('.thrift',)


class ResourceSources(Sources):
  extensions = tuple()


class Requirement(Struct):
  """A setuptools requirement."""

  def __init__(self, req, repo=None, **kwargs):
    """
    :param string req: A setuptools compatible requirement specifier; eg: `pantsbuild.pants>0.0.42`.
    :param string repo: An optional custom find-links repo URL.
    """
    super(Requirement, self).__init__(req=req, repo=repo, **kwargs)


class Classpath(object):
  # Placeholder product.
  pass


class Jar(Struct):
  """A java jar."""

  def __init__(self, org=None, name=None, rev=None, **kwargs):
    """
    :param string org: The Maven ``groupId`` of this dependency.
    :param string name: The Maven ``artifactId`` of this dependency; also serves as the name portion
                        of the address of this jar if defined at the top level of a BUILD file.
    :param string rev: The Maven ``version`` of this dependency.
    """
    super(Jar, self).__init__(org=org, name=name, rev=rev, **kwargs)


@printing_func
def ivy_resolve(jars):
  pass


@printing_func
def isolate_resources(resources):
  """Copies resources into a private directory, and provides them as a Classpath entry."""
  pass


class ThriftConfiguration(StructWithDeps):
  pass


class ApacheThriftConfiguration(ThriftConfiguration):
  def __init__(self, rev=None, strict=True, **kwargs):
    """
    :param string rev: The version of the apache thrift compiler to use.
    :param bool strict: `False` to turn strict compiler warnings off (not recommended).
    """
    super(ApacheThriftJavaConfiguration, self).__init__(rev=rev, strict=strict, **kwargs)


class ApacheThriftJavaConfiguration(ApacheThriftConfiguration):
  pass


class ApacheThriftPythonConfiguration(ApacheThriftConfiguration):
  pass


class ApacheThriftError(TaskError):
  pass


@printing_func
def gen_apache_thrift(sources, rev, gen, strict):
  if rev == 'fail':
    raise ApacheThriftError('Failed to generate via apache thrift for sources: {}, rev: {}, '
                            'gen:{}, strict: {}'.format(sources, rev, gen, strict))


class BuildPropertiesConfiguration(Struct):
  pass


def write_name_file(name):
  # Write a file containing the name in CWD
  with safe_open('build.properties') as f:
    f.write('name={}\n'.format(name))


class ScroogeConfiguration(ThriftConfiguration):
  def __init__(self, rev=None, strict=True, **kwargs):
    """
    :param string rev: The version of the scrooge compiler to use.
    :param bool strict: `False` to turn strict compiler warnings off (not recommended).
    """
    super(ScroogeScalaConfiguration, self).__init__(rev=rev, strict=strict, **kwargs)


class ScroogeScalaConfiguration(ScroogeConfiguration):
  pass


class ScroogeJavaConfiguration(ScroogeConfiguration):
  pass


@printing_func
def gen_scrooge_thrift(sources, scrooge_classpath, lang, strict):
  pass


@printing_func
def javac(sources, classpath):
  pass


@printing_func
def scalac(sources, classpath):
  pass


# TODO(John Sirois): When https://github.com/pantsbuild/pants/issues/2413 is resolved, move the
# unpickleable input and output test planners below to engine test.  There will be less setup
# required at that point since no target addresses will need to be supplied in the build_request.
class UnpickleableInput(object):
  pass


class UnpickleableResult(object):
  pass


def unpickleable_func():
  # Nested functions like this lambda are unpicklable.
  return lambda: None


def setup_json_scheduler(build_root):
  """Return a build graph and scheduler configured for BLD.json files under the given build root.

  :rtype tuple of (:class:`pants.engine.exp.graph.Graph`,
                   :class:`pants.engine.exp.scheduler.LocalScheduler`)
  """
  symbol_table = {'apache_thrift_java_configuration': ApacheThriftJavaConfiguration,
                  'apache_thrift_python_configuration': ApacheThriftPythonConfiguration,
                  'jar': Jar,
                  'requirement': Requirement,
                  'scrooge_java_configuration': ScroogeJavaConfiguration,
                  'scrooge_scala_configuration': ScroogeScalaConfiguration,
                  'java': JavaSources,
                  'python': PythonSources,
                  'resources': ResourceSources,
                  'scala': ScalaSources,
                  'thrift': ThriftSources,
                  'target': Target,
                  'build_properties': BuildPropertiesConfiguration}
  json_parser = functools.partial(parse_json, symbol_table=symbol_table)
  graph = Graph(AddressMapper(build_root=build_root,
                              build_pattern=r'^BLD.json$',
                              parser=json_parser))

  # TODO(John Sirois): once the options system is plumbed, make the tool spec configurable.
  # It could also just be pointed at the scrooge jar at that point.
  scrooge_tool_address = Address.parse('src/scala/scrooge')

  products_by_goal = {
      'compile': [Classpath],
      # TODO: to allow for running resolve alone, should split out a distinct 'IvyReport' product.
      'resolve': [Classpath],
      'gen': [JavaSources, PythonSources, ResourceSources, ScalaSources],
      'unpickleable': [UnpickleableResult],
    }
  tasks = [
      (JavaSources,
       [SelectSubject(ThriftSources),
        SelectSubject(ApacheThriftJavaConfiguration)],
       gen_apache_thrift),
      (PythonSources,
       [SelectSubject(ThriftSources),
        SelectSubject(ApacheThriftPythonConfiguration)],
       gen_apache_thrift),
      (ScalaSources,
       [SelectSubject(ThriftSources),
        SelectSubject(ScroogeScalaConfiguration),
        SelectAddress(scrooge_tool_address, Classpath)],
       gen_scrooge_thrift),
      (JavaSources,
       [SelectSubject(ThriftSources),
        SelectSubject(ScroogeJavaConfiguration),
        SelectAddress(scrooge_tool_address, Classpath)],
       gen_scrooge_thrift),
      (Classpath,
       [SelectSubject(Jar)],
       ivy_resolve),
      (Classpath,
       [SelectSubject(ResourceSources)],
       isolate_resources),
      (Classpath,
       [SelectSubject(BuildPropertiesConfiguration)],
       write_name_file),
      (Classpath,
       [SelectSubject(JavaSources),
        SelectDependencies(Classpath, JavaSources)],
       javac),
      (Classpath,
       [SelectSubject(ScalaSources),
        SelectDependencies(Classpath, ScalaSources)],
       scalac),
      (UnpickleableInput,
        [],
        unpickleable_func),
      (UnpickleableResult,
       [SelectSubject(UnpickleableInput)],
       unpickleable_func),
    ]
  scheduler = LocalScheduler(graph, products_by_goal, tasks)
  return graph, scheduler
