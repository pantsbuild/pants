# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import re

from twitter.common.dirutil import Fileset
from twitter.common.lang import AbstractClass, Compatibility

from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.build_environment import get_buildroot
from pants.base.build_manual import manual
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import BundlePayload
from pants.base.target import Target
from pants.base.validation import assert_list


class JarRule(AbstractClass):
  def __init__(self, apply_pattern):
    if not isinstance(apply_pattern, Compatibility.string):
      raise ValueError('The supplied apply_pattern is not a string, given: %s' % apply_pattern)
    try:
      self._apply_pattern = re.compile(apply_pattern)
    except re.error as e:
      raise ValueError('The supplied apply_pattern - %s - is not a valid regular expression: %s'
                       % (apply_pattern, e))

  @property
  def apply_pattern(self):
    """The pattern that matches jar entry paths this rule applies to."""
    return self._apply_pattern


class Skip(JarRule):
  """A rule that skips adding matched entries to a jar."""


class Duplicate(JarRule):
  """A rule that indicates how duplicate entries should be handled when building a jar."""

  class Error(Exception):
    """Raised by the ``FAIL`` action when a duplicate entry is encountered"""
    def __init__(self, path):
      """Creates a duplicate entry error for the given path.

      :param str path: The path of the duplicate entry.
      """
      assert path and isinstance(path, Compatibility.string), 'A non-empty path must be supplied.'
      super(Duplicate.Error, self).__init__('Duplicate entry encountered for path %s' % path)
      self._path = path

    @property
    def path(self):
      """The path of the duplicate entry."""
      return self._path

  SKIP = object()
  """Retains the 1st entry and skips subsequent duplicates."""

  REPLACE = object()
  """Retains the most recent entry and skips prior duplicates."""

  CONCAT = object()
  """Concatenates the contents of all duplicate entries encountered in the order encountered."""

  FAIL = object()
  """Raises a :class:``Duplicate.Error`` when a duplicate entry is
  encountered.
  """

  _VALID_ACTIONS = frozenset((SKIP, REPLACE, CONCAT, FAIL))

  @classmethod
  def validate_action(cls, action):
    """Verifies the given action is a valid duplicate jar rule action.

    :returns: The action if it is valid.
    :raises: ``ValueError`` if the action is invalid.
    """
    if action not in cls._VALID_ACTIONS:
      raise ValueError('The supplied action must be one of %s, given: %s'
                       % (cls._VALID_ACTIONS, action))
    return action

  def __init__(self, apply_pattern, action):
    """Creates a rule for handling duplicate jar entries.

    :param str apply_pattern: A regular expression that matches duplicate jar entries this rule
      applies to.
    :param action: An action to take to handle one or more duplicate entries.  Must be one of:
      ``Duplicate.SKIP``, ``Duplicate.REPLACE``, ``Duplicate.CONCAT`` or ``Duplicate.FAIL``.
    """
    super(Duplicate, self).__init__(apply_pattern)

    self._action = self.validate_action(action)

  @property
  def action(self):
    """The action to take for any duplicate entries that match this rule's ``apply_pattern``."""
    return self._action


class JarRules(object):
  """A set of rules for packaging up a deploy jar.

  Deploy jars are executable jars with fully self-contained classpaths and as such, assembling them
  presents problems given jar semantics.

  One issue is signed jars that must be included on the
  classpath.  These have a signature that depends on the jar contents and assembly of the deploy jar
  changes the content of the jar, breaking the signatures.  For cases like these the signed jars
  must be verified and then the signature information thrown away.  The :ref:`Skip <bdict_Skip>`
  rule supports this sort of issue by allowing outright entry exclusion in the final deploy jar.

  Another issue is duplicate jar entries.  Although the underlying zip format supports these, the
  java jar tool and libraries do not.  As such some action must be taken for each duplicate entry
  such that there are no duplicates in the final deploy jar.  The four
  :ref:`Duplicate <bdict_Duplicate>` rules support resolution of these cases by allowing 1st wins,
  last wins, concatenation of the duplicate entry contents or raising an exception.
  """
  @classmethod
  def skip_signatures_and_duplicates_concat_well_known_metadata(cls, default_dup_action=None,
                                                                additional_rules=None):
    """Produces a rule set useful in many deploy jar creation contexts.

    The rule set skips duplicate entries by default, retaining the 1st encountered.  In addition it
    has the following special handling:

    - jar signature metadata is dropped
    - ``java.util.ServiceLoader`` provider-configuration files are concatenated in the order
      encountered

    :param default_dup_action: An optional default action to take for duplicates.  Defaults to
      `Duplicate.SKIP` if not specified.
    :param additional_rules: Optionally one or more jar rules to add to those described above.
    :returns: JarRules
    """
    default_dup_action = Duplicate.validate_action(default_dup_action or Duplicate.SKIP)
    additional_rules = assert_list(additional_rules, expected_type=(Duplicate, Skip))

    rules = [Skip(r'^META-INF/[^/]+\.SF$'),  # signature file
             Skip(r'^META-INF/[^/]+\.DSA$'),  # default signature alg. file
             Skip(r'^META-INF/[^/]+\.RSA$'),  # default signature alg. file
             Duplicate(r'^META-INF/services/', Duplicate.CONCAT)]  # 1 svc fqcn per line

    return cls(rules=rules + additional_rules, default_dup_action=default_dup_action)

  _DEFAULT = None

  @classmethod
  def default(cls):
    """Returns the default set of jar rules.

    Can be set with `set_default` but otherwise defaults to
    `skip_signatures_and_duplicates_concat_well_known_metadata`.
    """
    if cls._DEFAULT is None:
      cls._DEFAULT = cls.skip_signatures_and_duplicates_concat_well_known_metadata()
    return cls._DEFAULT

  @classmethod
  def set_default(cls, rules):
    """Sets the default site-wide jar rules."""
    if not isinstance(rules, JarRules):
      raise ValueError('The default rules must be a JarRules instance.')
    cls._DEFAULT = rules

  def __init__(self, rules=None, default_dup_action=Duplicate.SKIP):
    """Creates a new set of jar rules with the default duplicate action of ``Duplicate.SKIP``.

    :param rules: One or more rules that will be applied in order to jar entries being packaged in
      a deploy jar.
    :param default_dup_action: The default action to take when a duplicate entry is encountered and
      no explicit rules apply to the entry.
    """
    self._default_dup_action = Duplicate.validate_action(default_dup_action)
    self._rules = assert_list(rules, expected_type=JarRule)

  @property
  def default_dup_action(self):
    """The default action to take when a duplicate jar entry is encountered."""
    return self._default_dup_action

  @property
  def rules(self):
    """The list of explicit entry rules in effect."""
    return self._rules


class JvmBinary(JvmTarget):
  """Produces a JVM binary optionally identifying a launcher main class.

  Below are a summary of how key goals affect targets of this type:

  * ``bundle`` - Creates a self-contained directory with the binary and all
    its dependencies, optionally archived, suitable for deployment.
  * ``binary`` - Create an executable jar of the binary. On the JVM
    this means the jar has a manifest specifying the main class.
  * ``run`` - Executes the main class of this binary locally.
  """
  def __init__(self,
               name=None,
               main=None,
               basename=None,
               source=None,
               deploy_excludes=None,
               deploy_jar_rules=None,
               **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param string main: The name of the ``main`` class, e.g.,
      ``'com.pants.examples.hello.main.HelloMain'``. This class may be
      present as the source of this target or depended-upon library.
    :param string basename: Base name for the generated ``.jar`` file, e.g.,
      ``'hello'``. (By default, uses ``name`` param)
    :param string source: Name of one ``.java`` or ``.scala`` file (a good
      place for a ``main``).
    :param resources: List of ``resource``\s to include in bundle.
    :param dependencies: Targets (probably ``java_library`` and
     ``scala_library`` targets) to "link" in.
    :type dependencies: list of target specs
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param deploy_excludes: List of :ref:`exclude <bdict_exclude>`\s to apply
      at deploy time.
      If you, for example, deploy a java servlet that has one version of
      ``servlet.jar`` onto a Tomcat environment that provides another version,
      they might conflict. ``deploy_excludes`` gives you a way to build your
      code but exclude the conflicting ``jar`` when deploying.
    :param deploy_jar_rules: :ref:`Jar rules <bdict_jar_rules>` for packaging this binary in a
      deploy jar.
    :param configurations: Ivy configurations to resolve for this target.
      This parameter is not intended for general use.
    :type configurations: tuple of strings
    """
    sources = [source] if source else None
    super(JvmBinary, self).__init__(name=name, sources=self.assert_list(sources), **kwargs)

    if main and not isinstance(main, Compatibility.string):
      raise TargetDefinitionException(self, 'main must be a fully qualified classname')

    if source and not isinstance(source, Compatibility.string):
      raise TargetDefinitionException(self, 'source must be a single relative file path')

    # Consider an alias mechanism (target) that acts like JarLibrary but points to a single item
    # and admits any pointee type.  Its very likely folks will want to share jar_rules but they
    # cannot today and it seems heavy-handed to force jar_rules to be a target just to get an
    # address in the off chance its needed.
    if deploy_jar_rules and not isinstance(deploy_jar_rules, JarRules):
      raise TargetDefinitionException(self, 'deploy_jar_rules must be a JarRules specification')

    self.main = main
    self.basename = basename or name
    self.deploy_excludes = self.assert_list(deploy_excludes, expected_type=Exclude)
    self.deploy_jar_rules = deploy_jar_rules or JarRules.default()


class RelativeToMapper(object):
  """A mapper that maps files specified relative to a base directory."""

  def __init__(self, base):
    """The base directory files should be mapped from."""
    self.base = base

  def __call__(self, file):
    return os.path.relpath(file, self.base)

  def __repr__(self):
    return 'IdentityMapper(%s)' % self.base

  def __hash__(self):
    return hash(self.base)


class Bundle(object):
  """A set of files to include in an application bundle.

  To learn about application bundles, see :ref:`jvm_bundles`.
  Looking for Java-style resources accessible via the ``Class.getResource`` API?
  Those are :ref:`bdict_resources`\ .

  Files added to the bundle will be included when bundling an application target.
  By default relative paths are preserved. For example, to include ``config``
  and ``scripts`` directories: ::

    bundles=[
      bundle().add(rglobs('config/*', 'scripts/*')),
    ]

  To include files relative to some path component use the ``relative_to`` parameter.
  The following places the contents of ``common/config`` in a  ``config`` directory
  in the bundle. ::

    bundles=[
      bundle(relative_to='common').add(globs('common/config/*'))
    ]
  """

  @classmethod
  def factory(cls, parse_context):
    """Return a factory method that can create bundles rooted at the parse context path."""
    def bundle(**kwargs):
      return Bundle(parse_context, **kwargs)
    bundle.__doc__ = Bundle.__init__.__doc__
    return bundle

  def __init__(self, parse_context, rel_path=None, mapper=None, relative_to=None):
    """
    :param rel_path: Base path of the "source" file paths. By default, path of the
      BUILD file. Useful for assets that don't live in the source code repo.
    :param mapper: Function that takes a path string and returns a path string. Takes a path in
      the source tree, returns a path to use in the resulting bundle. By default, an identity
      mapper.
    :param string relative_to: Set up a simple mapping from source path to bundle path.
      E.g., ``relative_to='common'`` removes that prefix from all files in the application bundle.
    """
    if mapper and relative_to:
      raise ValueError("Must specify exactly one of 'mapper' or 'relative_to'")

    self._rel_path = rel_path or parse_context.rel_path
    self.filemap = {}

    if relative_to:
      base = os.path.join(get_buildroot(), self._rel_path, relative_to)
      if not os.path.isdir(os.path.join(get_buildroot(), base)):
        raise ValueError('Could not find a directory to bundle relative to at %s' % base)
      self.mapper = RelativeToMapper(base)
    else:
      self.mapper = mapper or RelativeToMapper(os.path.join(get_buildroot(), self._rel_path))

  @manual.builddict()
  def add(self, *filesets):
    """Add files to the bundle, where ``filesets`` is a filename, ``globs``, or ``rglobs``.
    Note this is a variable length param and may be specified any number of times.
    """
    for fileset in filesets:
      paths = fileset() if isinstance(fileset, Fileset) \
                        else fileset if hasattr(fileset, '__iter__') \
                        else [fileset]
      for path in paths:
        abspath = path
        if not os.path.isabs(abspath):
          abspath = os.path.join(get_buildroot(), self._rel_path, path)
        if not os.path.exists(abspath):
          raise ValueError('Given path: %s with absolute path: %s which does not exist'
                           % (path, abspath))
        self.filemap[abspath] = self.mapper(abspath)
    return self

  def __repr__(self):
    return 'Bundle(%s, %s)' % (self.mapper, self.filemap)


class JvmApp(Target):
  """A JVM-based application consisting of a binary plus "extra files".

  Invoking the ``bundle`` goal on one of these targets creates a
  self-contained artifact suitable for deployment on some other machine.
  The artifact contains the executable jar, its dependencies, and
  extra files like config files, startup scripts, etc.
  """

  def __init__(self, name=None, binary=None, bundles=None, basename=None, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param string binary: Target spec of the ``jvm_binary`` that contains the
      app main.
    :param bundles: One or more ``bundle``\s
      describing "extra files" that should be included with this app
      (e.g.: config files, startup scripts).
    :param string basename: Name of this application, if different from the
      ``name``. Pants uses this in the ``bundle`` goal to name the distribution
      artifact. In most cases this parameter is not necessary.
    """
    payload = BundlePayload(bundles)
    super(JvmApp, self).__init__(name=name, payload=payload, **kwargs)

    if name == basename:
      raise TargetDefinitionException(self, 'basename must not equal name.')
    self._basename = basename or name

    self._binary = binary

  @property
  def traversable_dependency_specs(self):
    return [self._binary] if self._binary else []

  @property
  def basename(self):
    return self._basename

  @property
  def bundles(self):
    return self.payload.bundles

  @property
  def binary(self):
    dependencies = self.dependencies
    if len(dependencies) != 1:
      raise TargetDefinitionException(self, 'A JvmApp must define exactly one JvmBinary '
                                            'dependency, have: %s' % dependencies)
    binary = dependencies[0]
    if not isinstance(binary, JvmBinary):
      raise TargetDefinitionException(self, 'Expected JvmApp binary dependency to be a JvmBinary '
                                            'target, found %s' % binary)
    return binary

  @property
  def jar_dependencies(self):
    return self.binary.jar_dependencies

  def is_jvm_app(self):
    return True
