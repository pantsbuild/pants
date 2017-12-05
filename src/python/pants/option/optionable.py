# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import re
from abc import abstractproperty
from builtins import str
from hashlib import sha1

from pants.engine.selectors import Get
from twitter.common.collections import OrderedSet

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.errors import OptionsError
from pants.option.scope import Scope, ScopedOptions, ScopeInfo
from pants.util.meta import AbstractClass, classproperty
from pants.util.memo import memoized_method, memoized_property


def _construct_optionable(optionable_factory):
  scope = optionable_factory.options_scope
  scoped_options = yield Get(ScopedOptions, Scope(str(scope)))
  yield optionable_factory.optionable_cls(scope, scoped_options.options)


class OptionableFactory(AbstractClass):
  """A mixin that provides a method that returns an @rule to construct subclasses of Optionable.

  Optionable subclasses constructed in this manner must have a particular constructor shape, which is
  loosely defined by `_construct_optionable` and `OptionableFactory.signature`.
  """

  @abstractproperty
  def optionable_cls(self):
    """The Optionable class that is constructed by this OptionableFactory."""

  @abstractproperty
  def options_scope(self):
    """The scope from which the ScopedOptions for the target Optionable will be parsed."""

  @classmethod
  def signature(cls):
    """Returns kwargs to construct a `TaskRule` that will construct the target Optionable.

    TODO: This indirection avoids a cycle between this module and the `rules` module.
    """
    snake_scope = cls.options_scope.replace('-', '_')
    partial_construct_optionable = functools.partial(_construct_optionable, cls)
    partial_construct_optionable.__name__ = 'construct_scope_{}'.format(snake_scope)
    return dict(
        output_type=cls.optionable_cls,
        input_selectors=tuple(),
        func=partial_construct_optionable,
        input_gets=(Get.create_statically_for_rule_graph(ScopedOptions, Scope),),
        dependency_optionables=(cls.optionable_cls,),
      )


class SubsystemDependency(namedtuple('_SubsystemDependency', ('subsystem_cls', 'scope'))):
  def subsystem_dependency_joined_scope(self):
    return self.subsystem_cls.subscope(self.scope)


class SubsystemClientError(Exception): pass


class Register(namedtuple('_Register', ('options', 'optionable', 'bootstrap', 'scope'))):
  def __call__(self, *args, **kwargs):
    kwargs['registering_class'] = self.optionable
    # print('args: {}, kwargs: {}'.format(args, kwargs))
    self.options.register(self.scope, *args, **kwargs)


class Optionable(OptionableFactory, AbstractClass):
  """A mixin for classes that can register options on some scope."""

  # Subclasses must override.
  options_scope = None
  options_scope_category = None

  # Subclasses may override these to specify a deprecated former name for this Optionable's scope.
  # Option values can be read from the deprecated scope, but a deprecation warning will be issued.
  # The deprecation warning becomes an error at the given Pants version (which must therefore be
  # a valid semver).
  deprecated_options_scope = None
  deprecated_options_scope_removal_version = None

  @classmethod
  def implementation_versions(cls):
    """
    :API: public
    """
    return []

  class CycleException(Exception):
    """Thrown when a circular dependency is detected."""

    def __init__(self, cycle):
      message = 'Cycle detected:\n\t{}'.format(' ->\n\t'.join(
          '{} scope: {}'.format(subsystem, subsystem.options_scope) for subsystem in cycle))
      super(Optionable.CycleException, self).__init__(message)

  @classmethod
  @memoized_method
  def implementation_version_str(cls):
    return '.'.join(['_'.join(map(str, x)) for x in cls.implementation_versions()])

  @classmethod
  @memoized_method
  def implementation_version_slug(cls):
    return sha1(cls.implementation_version_str().encode('utf-8')).hexdigest()[:12]

  # We set this explicitly on the synthetic subclass, so that it shares a stable name with
  # its superclass, which is not necessary for regular use, but can be convenient in tests.
  _stable_name = None
  @classmethod
  def stable_name(cls):
    """The stable name of this task type.

    We synthesize subclasses of the task types at runtime, and these synthesized subclasses
    may have random names (e.g., in tests), so this gives us a stable name to use across runs,
    e.g., in artifact cache references.
    """
    return cls._stable_name or cls._compute_stable_name()

  @classmethod
  def _compute_stable_name(cls):
    return '{}_{}'.format(cls.__module__, cls.__name__).replace('.', '_')

  @classmethod
  def subsystem_dependencies(cls):
    """The subsystems this object uses.

    Override to specify your subsystem dependencies. Always add them to your superclass's value.

    Note: Do not call this directly to retrieve dependencies. See subsystem_dependencies_iter().

    :return: A tuple of SubsystemDependency instances.
             In the common case where you're an optionable and you want to get an instance scoped
             to you, call subsystem_cls.scoped(cls) to get an appropriate SubsystemDependency.
             As a convenience, you may also provide just a subsystem_cls, which is shorthand for
             SubsystemDependency(subsystem_cls, GLOBAL SCOPE) and indicates that we want to use
             the global instance of that subsystem.
    """
    return tuple()

  @classmethod
  def subsystem_dependencies_iter(cls):
    """Iterate over the direct subsystem dependencies of this Optionable."""
    for dep in cls.subsystem_dependencies():
      if isinstance(dep, SubsystemDependency):
        yield dep
      else:
        yield SubsystemDependency(dep, GLOBAL_SCOPE, removal_version=None, removal_hint=None)

  @classmethod
  def subsystem_closure_iter(cls):
    """Iterate over the transitive closure of subsystem dependencies of this Optionable.

    :rtype: :class:`collections.Iterator` of :class:`SubsystemDependency`
    :raises: :class:`pants.subsystem.subsystem_client_mixin.SubsystemClientMixin.CycleException`
             if a dependency cycle is detected.
    """
    seen = set()
    dep_path = OrderedSet()

    def iter_subsystem_closure(subsystem_cls):
      if subsystem_cls in dep_path:
        raise cls.CycleException(list(dep_path) + [subsystem_cls])
      dep_path.add(subsystem_cls)

      for dep in subsystem_cls.subsystem_dependencies_iter():
        if dep not in seen:
          seen.add(dep)
          yield dep
          for d in iter_subsystem_closure(dep.subsystem_cls):
            yield d

      dep_path.remove(subsystem_cls)

    for dep in iter_subsystem_closure(cls):
      yield dep

  class CycleException(Exception):
    """Thrown when a circular subsystem dependency is detected."""

    def __init__(self, cycle):
      message = 'Cycle detected:\n\t{}'.format(' ->\n\t'.join(
        '{} scope: {}'.format(optionable_cls, optionable_cls.options_scope)
        for optionable_cls in cycle))
      super(SubsystemClientMixin.CycleException, self).__init__(message)

  def _options(self):
    return None

  @classmethod
  def subscope(cls, scope):
    if cls.options_scope is None or cls.options_scope_category is None:
      raise OptionsError(
        '{} must set options_scope and options_scope_category.'.format(cls.__name__))
    cls.validate_scope_name(cls.options_scope)
    if scope is None:
      raise OptionsError('TODO: err msg')
    if scope == GLOBAL_SCOPE:
      ret = cls.options_scope
    else:
      ret = '{0}.{1}'.format(cls.options_scope, scope)
    cls.validate_scope_name(ret)
    return ret

  @classmethod
  def get_scope_info(cls, subscope=None):
    """Returns a ScopeInfo instance representing this Optionable's options scope."""
    if subscope is None:
      combined_scope = cls.options_scope
    else:
      combined_scope = cls.subscope(subscope)
    return ScopeInfo(combined_scope, cls.options_scope_category, cls)

  # FIXME: add subscope arg and make this recursive!
  @classmethod
  def known_scope_infos(cls):
    """Yields ScopeInfo for all known scopes for this task, in no particular order."""
    # The task's own scope.
    yield cls.get_scope_info()
    # The scopes of any task-specific subsystems it uses.
    for dep in cls.subsystem_closure_iter():
      if not dep.scope == GLOBAL_SCOPE:
        yield dep.subsystem_cls.get_scope_info(subscope=dep.scope)

  @classmethod
  def closure_scope_info_strs(cls):
    q = [(ss, OrderedSet()) for ss in cls.subsystem_dependencies_iter()]
    known_subsystem_types = set()
    if cls.options_scope is None:
      raise Exception('TODO: err msg (cls: {})'.format(cls))
    known_scopes = set([cls.options_scope])

    while len(q) > 0:
      (sdep, ss_path) = q.pop()
      (ss, _) = sdep
      if ss in ss_path:
        cycle = list(ss_path) + [ss]
        raise cls.CycleException(cycle)
      if ss not in known_subsystem_types:
        known_subsystem_types.add(ss)
        joined_scope = sdep.subsystem_dependency_joined_scope()
        if joined_scope in known_scopes:
          raise Exception('TODO: err msg (joined_scope: {})'.format(joined_scope))
        known_scopes.add(joined_scope)
      for dep in ss.subsystem_dependencies_iter():
        q.append((dep, ss_path | [ss]))

    return known_scopes

  @memoized_property
  def fingerprint(self):
    hasher = sha1()
    hasher.update(self.stable_name())
    hasher.update(self.implementation_version_str())
    for scope_info in self.closure_scope_info_strs():
      hasher.update(scope_info)
    return str(hasher.hexdigest())

  @classmethod
  def supports_passthru_args(cls):
    return False

  _scope_name_component_re = re.compile(r'^(?:[a-z0-9])+(?:-(?:[a-z0-9])+)*$')

  @classproperty
  def optionable_cls(cls):
    # Fills the `OptionableFactory` contract.
    return cls

  @classmethod
  def is_valid_scope_name_component(cls, s):
    return cls._scope_name_component_re.match(s) is not None

  @classmethod
  def validate_scope_name_component(cls, s):
    if not cls.is_valid_scope_name_component(s):
      raise OptionsError('Options scope "{}" is not valid:\n'
                         'Replace in code with a new scope name consisting of dash-separated-words, '
                         'with words consisting only of lower-case letters and digits.'.format(s))

  _scope_name_re = re.compile(r'(?:(?:[a-z0-9])+(?:-(?:[a-z0-9])+)*(?:\.(?:[a-z0-9])+(?:-(?:[a-z0-9])+)*)*)?')

  @classmethod
  def is_valid_scope_name(cls, s):
    return s is None or cls._scope_name_re.match(s) is not None

  @classmethod
  def validate_scope_name(cls, s):
    if not cls.is_valid_scope_name(cls.options_scope):
      raise OptionsError('Options scope "{}" is not valid:\n'
                         'TODO: err msg'.format(cls.options_scope))

  @classmethod
  def subscope(cls, scope):
    """Create a subscope under this Optionable's scope."""
    return '{0}.{1}'.format(cls.options_scope, scope)

  @classmethod
  def known_scope_infos(cls):
    """Yields ScopeInfo for all known scopes for this optionable, in no particular order.

    Specific Optionable subtypes may override to provide information about other optionables.
    """
    yield cls.get_scope_info()

  @classmethod
  def get_options_scope_equivalent_flag_component(cls):
    """Return a string representing this optionable's scope as it would be in a command line flag.

    This method can be used to generate error messages with flags e.g. to fix some error with a
    pants command. These flags will then be as specific as possible, including e.g. all dependent
    subsystem scopes.
    """
    return re.sub(r'\.', '-', cls.options_scope)

  @classmethod
  def get_description(cls):
    # First line of docstring.
    return '' if cls.__doc__ is None else cls.__doc__.partition('\n')[0].strip()

  @classmethod
  def register_options(cls, register):
    """Register options for this optionable.

    Subclasses may override and call register(*args, **kwargs).
    """

  @classmethod
  def register_options_on_scope(cls, options):
    """Trigger registration of this optionable's options.

    Subclasses should not generally need to override this method.
    """
    cls.register_options(Register(options, cls, options.bootstrap_option_values(), cls.options_scope))

  def __init__(self):
    # Check that the instance's class defines options_scope.
    # Note: It is a bit odd to validate a class when instantiating an object of it. but checking
    # the class itself (e.g., via metaclass magic) turns out to be complicated, because
    # non-instantiable subclasses (such as TaskBase, Task, Subsystem and other domain-specific
    # intermediate classes) don't define options_scope, so we can only apply this check to
    # instantiable classes. And the easiest way to know if a class is instantiable is to hook into
    # its __init__, as we do here. We usually only create a single instance of an Optionable
    # subclass anyway.
    cls = type(self)
    if not isinstance(cls.options_scope, str):
      raise NotImplementedError('{} must set an options_scope class-level property.'.format(cls))
