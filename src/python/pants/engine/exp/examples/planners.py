# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import sys

from twitter.common.collections import OrderedSet

from pants.engine.exp.addressable import SubclassesOf, addressable_list
from pants.engine.exp.configuration import Configuration
from pants.engine.exp.graph import Graph
from pants.engine.exp.mapper import AddressMapper
from pants.engine.exp.parsers import parse_json
from pants.engine.exp.scheduler import GlobalScheduler, Plan, Planners, Subject, Task, TaskPlanner
from pants.engine.exp.targets import Sources as AddressableSources
from pants.engine.exp.targets import Target
from pants.util.memo import memoized


class PrintingTask(Task):
  @classmethod
  def fake_product(cls):
    return '<<<Fake{}Product>>>'.format(cls.__name__)

  def execute(self, **inputs):
    print('{} being executed with inputs: {}'.format(type(self).__name__, inputs))
    return self.fake_product()


class Requirement(Configuration):
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


class Jar(Configuration):
  """A java jar."""

  def __init__(self, org, name, rev=None, **kwargs):
    """
    :param string org: The Maven ``groupId`` of this dependency.
    :param string name: The Maven ``artifactId`` of this dependency; also serves as the name portion
                        of the address of this jar if defined at the top level of a BUILD file.
    :param string rev: The Maven ``version`` of this dependency.
    """
    super(Jar, self).__init__(org=org, name=name, rev=rev, **kwargs)


class GlobalIvyResolvePlanner(TaskPlanner):
  @property
  def goal_name(self):
    return 'resolve'

  @property
  def product_types(self):
    yield Classpath

  def plan(self, scheduler, product_type, subject):
    if isinstance(subject, Jar):
      # This plan is only used internally, the finalized plan will s/jar/jars/ for a single global
      # resolve.
      return Plan(task_type=IvyResolve, subjects=(subject,), jar=subject)

  def finalize_plans(self, plans):
    subjects = set()
    jars = OrderedSet()
    for plan in plans:
      subjects.update(plan.subjects)
      jars.add(plan.jar)
    global_plan = Plan(task_type=IvyResolve, subjects=subjects, jars=list(jars))
    return [global_plan]


class IvyResolve(PrintingTask):
  def execute(self, jars):
    return super(IvyResolve, self).execute(jars=jars)


def _create_sources(ext):
  # A pickle-compatible top-level function for custom unpickling of Sources per-extension types.
  return Sources.of(ext)


class Sources(object):
  @classmethod
  @memoized
  def of(cls, ext):
    type_name = b'Sources({!r})'.format(ext)

    class_dict = {'ext': ext,
                  # We need custom serialization for the dynamic class type.
                  '__reduce__': lambda self: (_create_sources, ext)}

    ext_type = type(type_name, (cls,), class_dict)

    # Expose the custom class type at the module level to be pickle compatible.
    setattr(sys.modules[cls.__module__], type_name, ext_type)

    return ext_type

  @classmethod
  def ext(cls):
    raise NotImplementedError()

  def __repr__(self):
    return 'Sources(ext={!r})'.format(self.ext)


class ApacheThriftConfiguration(Configuration):
  def __init__(self, rev, gen, strict=True, deps=None, **kwargs):
    """
    :param string rev: The version of the apache thrift compiler to use.
    :param string gen: The thrift compiler `--gen` argument specifying the type of code to generate
                       and any options to pass to the generator.
    :param bool strict: `False` to turn strict compiler warnings off (not recommended).
    :param deps: An optional list of dependencies needed by the generated code.
    :type deps: list of jars
    """
    super(ApacheThriftConfiguration, self).__init__(rev=rev, gen=gen, strict=strict, **kwargs)
    self.deps = deps

  # Could be Jars, PythonRequirements, ... we simply don't know a-priori - depends on --gen lang.
  @addressable_list(SubclassesOf(Configuration))
  def deps(self):
    """Return a list of the dependencies needed by the generated code."""


class ApacheThriftPlanner(TaskPlanner):

  def __init__(self):
    # This will come via an option default.
    # TODO(John Sirois): once the options system is plumbed, make the languages configurable.
    self._product_type_by_lang = {'java': Sources.of('.java'), 'py': Sources.of('.py')}

  @property
  def goal_name(self):
    return 'gen'

  @property
  def product_types(self):
    return self._product_type_by_lang.values()

  def _product_type(self, gen):
    lang = gen.partition(':')[0]
    return self._product_type_by_lang.get(lang)

  def plan(self, scheduler, product_type, subject):
    if not isinstance(subject, Target):
      return None

    thrift_sources = list(subject.sources.iter_paths(base_path=subject.address.spec_path,
                                                     ext='.thrift'))
    if not thrift_sources:
      return None

    configs = [config for config in subject.configurations
               if product_type == self._product_type(config.gen)]
    if not configs:
      # We don't know how to generate these type of sources for this subject.
      return None
    if len(configs) > 1:
      raise self.Error('Found more than one configuration for generating {!r} from {!r}:\n\t{}'
                       .format(product_type, subject, '\n\t'.join(repr(c) for c in configs)))
    config = configs[0]

    subject = Subject(subject, alternate=Target(dependencies=config.deps))
    return Plan(task_type=ApacheThrift,
                subjects=(subject,),
                sources=thrift_sources,
                rev=config.rev,
                gen=config.gen,
                strict=config.strict)


class ApacheThrift(PrintingTask):
  def execute(self, sources, rev, gen, strict):
    return super(ApacheThrift, self).execute(sources=sources, rev=rev, gen=gen, strict=strict)


class JavacPlanner(TaskPlanner):
  # Product type
  JavaSources = Sources.of('.java')

  @property
  def goal_name(self):
    return 'compile'

  @property
  def product_types(self):
    yield Classpath

  def plan(self, scheduler, product_type, subject):
    if not isinstance(subject, Target):
      return None

    sources = list(subject.sources.iter_paths(base_path=subject.address.spec_path, ext='.java'))
    if not sources:
      # TODO(John Sirois): Abstract a ~SourcesConsumerPlanner that can grab sources of given types
      # or else defer to a code generator like we do here.  As it stands, the planner must
      # explicitly allow for code generators and this repeated code / foresight can easily be
      # missed in new compilers, and other source-using tasks.  Once done though, code gen can be
      # introduced to any nesting depth, ie: code gen '.thrift' files.

      # This is a dep graph "hole", we depend on the thing but don't know what it is.  Either it
      # could be something that gets transformed in to java or transformed into a `Classpath`
      # by some other compiler targeting the jvm.
      sources = scheduler.promise(subject, self.JavaSources, required=False)
      if sources:
        subject = sources.subject

    if not sources:
      # We don't know how to compile this subject, someone else may (Scalac, Groovyc, ...)
      return None

    classpath_promises = []
    for derivation in Subject.as_subject(subject).iter_derivations:
      for dep in derivation.dependencies:
        # This could recurse to us (or be satisfied by IvyResolve, Scalac, etc. depending on the
        # dep type).
        internal_cp_promise = scheduler.promise(dep, Classpath)
        if internal_cp_promise:
          classpath_promises.append(internal_cp_promise)

    return Plan(task_type=JavacTask,
                subjects=(subject,),
                sources=sources,
                classpath=classpath_promises)


class JavacTask(PrintingTask):
  def execute(self, sources, classpath):
    return super(JavacTask, self).execute(sources=sources, classpath=classpath)


def setup_json_scheduler(build_root):
  """Return a build graph and scheduler configured for BLD.json files under the given build root.

  :rtype tuple of (:class:`pants.engine.exp.graph.Graph`,
                   :class:`pants.engine.exp.scheduler.GlobalScheduler`)
  """
  symbol_table = {'apache_thrift_configuration': ApacheThriftConfiguration,
                  'jar': Jar,
                  'requirement': Requirement,
                  'sources': AddressableSources,
                  'target': Target}
  json_parser = functools.partial(parse_json, symbol_table=symbol_table)
  graph = Graph(AddressMapper(build_root=build_root,
                              build_pattern=r'^BLD.json$',
                              parser=json_parser))

  planners = [ApacheThriftPlanner(), GlobalIvyResolvePlanner(), JavacPlanner()]
  global_scheduler = GlobalScheduler(graph, Planners(planners))
  return graph, global_scheduler
