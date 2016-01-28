# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import functools
from abc import abstractmethod, abstractproperty

import six
from twitter.common.collections import OrderedSet

from pants.base.exceptions import TaskError
from pants.build_graph.address import Address
from pants.engine.exp.graph import create_graph_tasks
from pants.engine.exp.mapper import AddressMapper
from pants.engine.exp.objects import datatype
from pants.engine.exp.parsers import JsonParser, SymbolTable
from pants.engine.exp.scheduler import (LocalScheduler, Select, SelectDependencies, SelectLiteral,
                                        SelectVariant)
from pants.engine.exp.struct import Struct, StructWithDeps
from pants.engine.exp.targets import Sources, Target
from pants.util.memo import memoized, memoized_property


def printing_func(func):
  @functools.wraps(func)
  def wrapper(*inputs):
    product = func(*inputs)
    return_val = product if product else '<<<Fake-{}-Product>>>'.format(func.__name__)
    print('{} executed for {}, returned: {}'.format(func.__name__, inputs, return_val))
    return return_val
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


class Classpath(Struct):
  """Placeholder product."""

  def __init__(self, creator, **kwargs):
    super(Classpath, self).__init__(creator=creator, **kwargs)


class ManagedResolve(Struct):
  """A frozen ivy resolve that when combined with a ManagedJar can produce a Jar."""

  def __init__(self, revs, **kwargs):
    """
    :param dict revs: A dict of artifact org#name to version.
    """
    super(ManagedResolve, self).__init__(revs=revs, **kwargs)

  def __repr__(self):
    return "ManagedResolve({})".format(self.revs)


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


class ManagedJar(Struct):
  """A java jar template, which can be merged with a ManagedResolve to determine a concrete version."""

  def __init__(self, org, name, **kwargs):
    """
    :param string org: The Maven ``groupId`` of this dependency.
    :param string name: The Maven ``artifactId`` of this dependency; also serves as the name portion
                        of the address of this jar if defined at the top level of a BUILD file.
    """
    super(ManagedJar, self).__init__(org=org, name=name, **kwargs)


@printing_func
def select_rev(managed_jar, managed_resolve):
  (org, name) = (managed_jar.org, managed_jar.name)
  rev = managed_resolve.revs.get('{}#{}'.format(org, name), None)
  if not rev:
    raise TaskError('{} does not have a managed version in {}.'.format(managed_jar, managed_resolve))
  return Jar(org=managed_jar.org, name=managed_jar.name, rev=rev)


@printing_func
def ivy_resolve(jars):
  return Classpath(creator='ivy_resolve')


@printing_func
def isolate_resources(resources):
  """Copies resources into a private directory, and provides them as a Classpath entry."""
  return Classpath(creator='isolate_resources')


class ThriftConfiguration(StructWithDeps):
  pass


class ApacheThriftConfiguration(ThriftConfiguration):
  def __init__(self, rev=None, strict=True, **kwargs):
    """
    :param string rev: The version of the apache thrift compiler to use.
    :param bool strict: `False` to turn strict compiler warnings off (not recommended).
    """
    super(ApacheThriftConfiguration, self).__init__(rev=rev, strict=strict, **kwargs)


class ApacheThriftJavaConfiguration(ApacheThriftConfiguration):
  pass


class ApacheThriftPythonConfiguration(ApacheThriftConfiguration):
  pass


class ApacheThriftError(TaskError):
  pass


@printing_func
def gen_apache_thrift(sources, config):
  if config.rev == 'fail':
    raise ApacheThriftError('Failed to generate via apache thrift for '
                            'sources: {}, config: {}'.format(sources, config))
  if isinstance(config, ApacheThriftJavaConfiguration):
    return JavaSources(files=['Fake.java'], dependencies=config.dependencies)
  elif isinstance(config, ApacheThriftPythonConfiguration):
    return PythonSources(files=['fake.py'], dependencies=config.dependencies)


class BuildPropertiesConfiguration(Struct):
  pass


@printing_func
def write_name_file(name):
  """Write a file containing the name of this target in the CWD."""
  return Classpath(creator='write_name_file')


class ScroogeConfiguration(ThriftConfiguration):
  def __init__(self, rev=None, strict=True, **kwargs):
    """
    :param string rev: The version of the scrooge compiler to use.
    :param bool strict: `False` to turn strict compiler warnings off (not recommended).
    """
    super(ScroogeConfiguration, self).__init__(rev=rev, strict=strict, **kwargs)


class ScroogeScalaConfiguration(ScroogeConfiguration):
  pass


class ScroogeJavaConfiguration(ScroogeConfiguration):
  pass


@printing_func
def gen_scrooge_thrift(sources, config, scrooge_classpath):
  if isinstance(config, ScroogeJavaConfiguration):
    return JavaSources(files=['Fake.java'], dependencies=config.dependencies)
  elif isinstance(config, ScroogeScalaConfiguration):
    return ScalaSources(files=['Fake.scala'], dependencies=config.dependencies)


@printing_func
def javac(sources, classpath):
  return Classpath(creator='javac')


@printing_func
def scalac(sources, classpath):
  return Classpath(creator='scalac')


# TODO(John Sirois): When https://github.com/pantsbuild/pants/issues/2413 is resolved, move the
# unpickleable input and output test planners below to engine test.  There will be less setup
# required at that point since no target addresses will need to be supplied in the build_request.
class UnpickleableOutput(object):
  pass


class UnpickleableResult(object):
  pass


def unpickleable_output():
  """Generates an unpickleable output."""
  # Nested functions like this lambda are unpicklable.
  return lambda: None


def unpickleable_input(unpickleable):
  raise Exception('This function should never run, because its selected input is unpickleable.')


class ExampleTable(SymbolTable):
  @classmethod
  def table(cls):
    return {'apache_thrift_java_configuration': ApacheThriftJavaConfiguration,
            'apache_thrift_python_configuration': ApacheThriftPythonConfiguration,
            'jar': Jar,
            'managed_jar': ManagedJar,
            'managed_resolve': ManagedResolve,
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


def setup_json_scheduler(build_root):
  """Return a build graph and scheduler configured for BLD.json files under the given build root.

  :rtype :class:`pants.engine.exp.scheduler.LocalScheduler`
  """
  address_mapper = AddressMapper(build_root=build_root,
                                 symbol_table_cls=ExampleTable,
                                 build_pattern=r'^BLD.json$',
                                 parser_cls=JsonParser)

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
       [Select(ThriftSources),
        SelectVariant(ApacheThriftJavaConfiguration, 'thrift')],
       gen_apache_thrift),
      (PythonSources,
       [Select(ThriftSources),
        SelectVariant(ApacheThriftPythonConfiguration, 'thrift')],
       gen_apache_thrift),
      (ScalaSources,
       [Select(ThriftSources),
        SelectVariant(ScroogeScalaConfiguration, 'thrift'),
        SelectLiteral(scrooge_tool_address, Classpath)],
       gen_scrooge_thrift),
      (JavaSources,
       [Select(ThriftSources),
        SelectVariant(ScroogeJavaConfiguration, 'thrift'),
        SelectLiteral(scrooge_tool_address, Classpath)],
       gen_scrooge_thrift),
      (Classpath,
       [Select(Jar)],
       ivy_resolve),
      (Jar,
       [Select(ManagedJar),
        SelectVariant(ManagedResolve, 'resolve')],
       select_rev),
      (Classpath,
       [Select(ResourceSources)],
       isolate_resources),
      (Classpath,
       [Select(BuildPropertiesConfiguration)],
       write_name_file),
      (Classpath,
       [Select(JavaSources),
        SelectDependencies(Classpath, JavaSources)],
       javac),
      (Classpath,
       [Select(ScalaSources),
        SelectDependencies(Classpath, ScalaSources)],
       scalac),
      (UnpickleableOutput,
        [],
        unpickleable_output),
      (UnpickleableResult,
       [Select(UnpickleableOutput)],
       unpickleable_input),
    ]
  scheduler = LocalScheduler(products_by_goal, tasks + create_graph_tasks(address_mapper))
  return scheduler
