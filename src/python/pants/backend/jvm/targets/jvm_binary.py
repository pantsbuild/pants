# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
from hashlib import sha1

from six import string_types

from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import (ExcludesField, FingerprintedField, FingerprintedMixin,
                                      PrimitiveField)
from pants.base.validation import assert_list
from pants.util.meta import AbstractClass


class JarRule(FingerprintedMixin, AbstractClass):

  def __init__(self, apply_pattern, payload=None):
    self.payload = payload or Payload()
    if not isinstance(apply_pattern, string_types):
      raise ValueError('The supplied apply_pattern is not a string, given: {}'
                       .format(apply_pattern))
    try:
      self._apply_pattern = re.compile(apply_pattern)
    except re.error as e:
      raise ValueError('The supplied apply_pattern: {pattern} '
                       'is not a valid regular expression: {msg}'
                       .format(pattern=apply_pattern, msg=e))
    self.payload.add_fields({
      'apply_pattern': PrimitiveField(apply_pattern),
    })

  def fingerprint(self):
    return self.payload.fingerprint()

  @property
  def apply_pattern(self):
    """The pattern that matches jar entry paths this rule applies to.

    :rtype: re.RegexObject
    """
    return self._apply_pattern


class Skip(JarRule):
  """A rule that skips adding matched entries to a jar."""

  def __repr__(self):
    return "Skip(apply_pattern={})".format(self.payload.apply_pattern)


class Duplicate(JarRule):
  """A rule that indicates how duplicate entries should be handled when building a jar."""

  class Error(Exception):
    """Raised by the ``FAIL`` action when a duplicate entry is encountered"""

    def __init__(self, path):
      """Creates a duplicate entry error for the given path.

      :param string path: The path of the duplicate entry.
      """
      assert path and isinstance(path, string_types), 'A non-empty path must be supplied.'
      super(Duplicate.Error, self).__init__('Duplicate entry encountered for path {}'.format(path))
      self._path = path

    @property
    def path(self):
      """The path of the duplicate entry."""
      return self._path

  SKIP = 'SKIP'
  """Retains the 1st entry and skips subsequent duplicates."""

  REPLACE = 'REPLACE'
  """Retains the most recent entry and skips prior duplicates."""

  CONCAT = 'CONCAT'
  """Concatenates the contents of all duplicate entries encountered in the order encountered."""

  CONCAT_TEXT = 'CONCAT_TEXT'
  """Concatenates the contents of all duplicate entries encountered in the order encountered,
  separating entries with newlines if needed.
  """

  FAIL = 'FAIL'
  """Raises a :class:``Duplicate.Error`` when a duplicate entry is
  encountered.
  """

  _VALID_ACTIONS = frozenset((SKIP, REPLACE, CONCAT, CONCAT_TEXT, FAIL))

  @classmethod
  def validate_action(cls, action):
    """Verifies the given action is a valid duplicate jar rule action.

    :returns: The action if it is valid.
    :raises: ``ValueError`` if the action is invalid.
    """
    if action not in cls._VALID_ACTIONS:
      raise ValueError('The supplied action must be one of {valid}, given: {given}'
                       .format(valid=cls._VALID_ACTIONS, given=action))
    return action

  def __init__(self, apply_pattern, action):
    """Creates a rule for handling duplicate jar entries.

    :param string apply_pattern: A regular expression that matches duplicate jar entries this rule
      applies to.
    :param action: An action to take to handle one or more duplicate entries.  Must be one of:
      ``Duplicate.SKIP``, ``Duplicate.REPLACE``, ``Duplicate.CONCAT``, ``Duplicate.CONCAT_TEXT``,
      or ``Duplicate.FAIL``.
    """
    payload = Payload()
    payload.add_fields({
      'action': PrimitiveField(self.validate_action(action)),
    })
    super(Duplicate, self).__init__(apply_pattern, payload=payload)

  @property
  def action(self):
    """The action to take for any duplicate entries that match this rule's ``apply_pattern``."""
    return self.payload.action

  def fingerprint(self):
    return self.payload.fingerprint()

  def __repr__(self):
    return "Duplicate(apply_pattern={0}, action={1})".format(self.payload.apply_pattern,
                                                             self.payload.action)


class JarRules(FingerprintedMixin):
  """A set of rules for packaging up a deploy jar.

  Deploy jars are executable jars with fully self-contained classpaths and as such, assembling them
  presents problems given jar semantics.

  One issue is signed jars that must be included on the
  classpath.  These have a signature that depends on the jar contents and assembly of the deploy jar
  changes the content of the jar, breaking the signatures.  For cases like these the signed jars
  must be verified and then the signature information thrown away.  The `Skip <#Skip>`_
  rule supports this sort of issue by allowing outright entry exclusion in the final deploy jar.

  Another issue is duplicate jar entries.  Although the underlying zip format supports these, the
  java jar tool and libraries do not.  As such some action must be taken for each duplicate entry
  such that there are no duplicates in the final deploy jar.  The four
  `Duplicate <#Duplicate>`_ rules support resolution of these cases by allowing 1st wins,
  last wins, concatenation of the duplicate entry contents or raising an exception.
  """

  @classmethod
  def skip_signatures_and_duplicates_concat_well_known_metadata(cls, default_dup_action=None,
                                                                additional_rules=None):
    """Produces a rule set useful in many deploy jar creation contexts.

    The rule set skips duplicate entries by default, retaining the 1st encountered.  In addition it
    has the following special handling:

    - jar signature metadata is dropped
    - jar indexing files INDEX.LIST are dropped
    - ``java.util.ServiceLoader`` provider-configuration files are concatenated in the order
      encountered

    :param default_dup_action: An optional default action to take for duplicates.  Defaults to
      `Duplicate.SKIP` if not specified.
    :param additional_rules: Optionally one or more jar rules to add to those described above.
    :returns: JarRules
    """
    default_dup_action = Duplicate.validate_action(default_dup_action or Duplicate.SKIP)
    additional_rules = assert_list(additional_rules,
                                   expected_type=(Duplicate, Skip))

    rules = [Skip(r'^META-INF/[^/]+\.SF$'),  # signature file
             Skip(r'^META-INF/[^/]+\.DSA$'),  # default signature alg. file
             Skip(r'^META-INF/[^/]+\.RSA$'),  # default signature alg. file
             Skip(r'^META-INF/INDEX.LIST$'),  # interferes with Class-Path: see man jar for i option
             Duplicate(r'^META-INF/services/', Duplicate.CONCAT_TEXT)]  # 1 svc fqcn per line

    return JarRules(rules=rules + additional_rules, default_dup_action=default_dup_action)

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
      a deploy jar. `Skip <#Skip>`_ rules can go here.
    :param default_dup_action: The default action to take when a duplicate entry is encountered and
      no explicit rules apply to the entry.
    """
    self.payload = Payload()
    self.payload.add_fields({
      'default_dup_action': PrimitiveField(Duplicate.validate_action(default_dup_action))
    })
    self._rules = assert_list(rules, expected_type=JarRule, key_arg="rules")

  @property
  def default_dup_action(self):
    """The default action to take when a duplicate jar entry is encountered."""
    return self.payload.default_dup_action

  @property
  def rules(self):
    """A copy of the list of explicit entry rules in effect."""
    return list(self._rules)

  def fingerprint(self):
    hasher = sha1()
    hasher.update(self.payload.fingerprint())
    for rule in self.rules:
      hasher.update(rule.fingerprint())
    return hasher.hexdigest()

  @property
  def value(self):
    return self._jar_rules


class ManifestEntries(FingerprintedMixin):
  """Describes additional items to add to the app manifest."""

  class ExpectedDictionaryError(Exception):
    pass

  def __init__(self, entries=None):
    """
    :param entries: Additional headers, value pairs to add to the MANIFEST.MF.
      You can just add fixed string header / value pairs.
    :type entries: dictionary of string : string
    """
    self.payload = Payload()
    if entries:
      if not isinstance(entries, dict):
        raise self.ExpectedDictionaryError("entries must be a dictionary of strings.")
      for key in entries.keys():
        if not isinstance(key, string_types):
          raise self.ExpectedDictionaryError(
            "entries must be dictionary of strings, got key {} type {}"
            .format(key, type(key).__name__))
    self.payload.add_fields({
      'entries': PrimitiveField(entries or {}),
      })

  def fingerprint(self):
    return self.payload.fingerprint()

  @property
  def entries(self):
    return self.payload.entries


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
               address=None,
               payload=None,
               main=None,
               basename=None,
               source=None,
               deploy_excludes=None,
               deploy_jar_rules=None,
               manifest_entries=None,
               shading_rules=None,
               **kwargs):
    """
    :param string main: The name of the ``main`` class, e.g.,
      ``'org.pantsbuild.example.hello.main.HelloMain'``. This class may be
      present as the source of this target or depended-upon library.
    :param string basename: Base name for the generated ``.jar`` file, e.g.,
      ``'hello'``. (By default, uses ``name`` param)
    :param string source: Name of one ``.java`` or ``.scala`` file (a good
      place for a ``main``).
    :param dependencies: Targets (probably ``java_library`` and
     ``scala_library`` targets) to "link" in.
    :type dependencies: list of target specs
    :param deploy_excludes: List of `exclude <#exclude>`_\s to apply
      at deploy time.
      If you, for example, deploy a java servlet that has one version of
      ``servlet.jar`` onto a Tomcat environment that provides another version,
      they might conflict. ``deploy_excludes`` gives you a way to build your
      code but exclude the conflicting ``jar`` when deploying.
    :param deploy_jar_rules: `Jar rules <#jar_rules>`_ for packaging this binary in a
      deploy jar.
    :param manifest_entries: dict that specifies entries for `ManifestEntries <#manifest_entries>`_
      for adding to MANIFEST.MF when packaging this binary.
    :param list shading_rules: Optional list of shading rules to apply when building a shaded
      (aka monolithic aka fat) binary jar. The order of the rules matters: the first rule which
      matches a fully-qualified class name is used to shade it. See shading_relocate(),
      shading_exclude(), shading_relocate_package(), and shading_exclude_package().
    """
    self.address = address  # Set in case a TargetDefinitionException is thrown early
    if main and not isinstance(main, string_types):
      raise TargetDefinitionException(self, 'main must be a fully qualified classname')
    if source and not isinstance(source, string_types):
      raise TargetDefinitionException(self, 'source must be a single relative file path')
    if deploy_jar_rules and not isinstance(deploy_jar_rules, JarRules):
      raise TargetDefinitionException(self,
                                      'deploy_jar_rules must be a JarRules specification. got {}'
                                      .format(type(deploy_jar_rules).__name__))
    if manifest_entries and not isinstance(manifest_entries, dict):
      raise TargetDefinitionException(self,
                                      'manifest_entries must be a dict. got {}'
                                      .format(type(manifest_entries).__name__))
    sources = [source] if source else None
    if 'sources' in kwargs:
      raise self.IllegalArgument(address.spec,
        'jvm_binary only supports a single "source" argument, typically used to specify a main '
        'class source file. Other sources should instead be placed in a java_library, which '
        'should be referenced in the jvm_binary\'s dependencies.'
      )
    payload = payload or Payload()
    payload.add_fields({
      'basename': PrimitiveField(basename or name),
      'deploy_excludes': ExcludesField(self.assert_list(deploy_excludes,
                                                        expected_type=Exclude,
                                                        key_arg='deploy_excludes')),
      'deploy_jar_rules': FingerprintedField(deploy_jar_rules or JarRules.default()),
      'manifest_entries': FingerprintedField(ManifestEntries(manifest_entries)),
      'main': PrimitiveField(main),
      'shading_rules': PrimitiveField(shading_rules or ()),
    })

    super(JvmBinary, self).__init__(name=name,
                                    address=address,
                                    payload=payload,
                                    sources=self.assert_list(sources, key_arg='sources'),
                                    **kwargs)

  @property
  def basename(self):
    return self.payload.basename

  @property
  def deploy_excludes(self):
    return self.payload.deploy_excludes

  @property
  def deploy_jar_rules(self):
    return self.payload.deploy_jar_rules

  @property
  def shading_rules(self):
    return self.payload.shading_rules

  @property
  def main(self):
    return self.payload.main

  @property
  def manifest_entries(self):
    return self.payload.manifest_entries
