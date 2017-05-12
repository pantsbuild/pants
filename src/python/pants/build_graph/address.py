# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import namedtuple

from pants.base.deprecated import deprecated, deprecated_conditional
from pants.util.dirutil import longest_dir_prefix
from pants.util.strutil import strip_prefix


# @ is reserved for configuring variant, see `addressable.parse_variants`
BANNED_CHARS_IN_TARGET_NAME = frozenset('@')


def parse_spec(spec, relative_to=None, subproject_roots=None):
  """Parses a target address spec and returns the path from the root of the repo to this Target
  and Target name.

  :API: public

  :param string spec: Target address spec.
  :param string relative_to: path to use for sibling specs, ie: ':another_in_same_build_family',
    interprets the missing spec_path part as `relative_to`.
  :param list subproject_roots: Paths that correspond with embedded build roots under
    the current build root.

  For Example::

    some_target(name='mytarget',
      dependencies=['path/to/buildfile:targetname']
    )

  Where ``path/to/buildfile:targetname`` is the dependent target address spec

  In case the target name is empty it returns the last component of the path as target name, ie::

    spec_path, target_name = parse_spec('path/to/buildfile/foo')

  Will return spec_path as 'path/to/buildfile/foo' and target_name as 'foo'.

  Optionally, specs can be prefixed with '//' to denote an absolute spec path.  This is normally
  not significant except when a spec referring to a root level target is needed from deeper in
  the tree.  For example, in ``path/to/buildfile/BUILD``::

    some_target(name='mytarget',
      dependencies=[':targetname']
    )

  The ``targetname`` spec refers to a target defined in ``path/to/buildfile/BUILD*``.  If instead
  you want to reference ``targetname`` in a root level BUILD file, use the absolute form.
  For example::

    some_target(name='mytarget',
      dependencies=['//:targetname']
    )
  """
  def normalize_absolute_refs(ref):
    return strip_prefix(ref, '//')

  subproject = longest_dir_prefix(relative_to, subproject_roots) if subproject_roots else None

  def prefix_subproject(spec_path):
    if not subproject:
      return spec_path
    elif spec_path:
      return os.path.join(subproject, spec_path)
    else:
      return os.path.normpath(subproject)

  spec_parts = spec.rsplit(':', 1)
  if len(spec_parts) == 1:
    spec_path = prefix_subproject(normalize_absolute_refs(spec_parts[0]))
    target_name = os.path.basename(spec_path)
  else:
    spec_path, target_name = spec_parts
    if not spec_path and not subproject and relative_to:
      spec_path = relative_to
    spec_path = prefix_subproject(normalize_absolute_refs(spec_path))

  return spec_path, target_name


class Addresses(namedtuple('Addresses', ['addresses', 'rel_path'])):
  """ Used as a sentinel type for identifying a list of string specs.

  addresses: list of string specs
  rel_path: addresses might be relative specs, so they need to be interpreted
  relative to the path of the BUILD file they were declared in.

  :API: public
  """


class InvalidSpecPath(ValueError):
  """Indicate an invalid spec path for `Address`."""


class InvalidTargetName(ValueError):
  """Indicate an invalid target name for `Address`."""


class Address(object):
  """A target address.

  An address is a unique name representing a
  :class:`pants.build_graph.target.Target`. It's composed of the
  path from the root of the repo to the Target plus the target name.

  While not their only use, a noteworthy use of addresses is specifying
  target dependencies. For example:

  ::

    some_target(name='mytarget',
      dependencies=['path/to/buildfile:targetname']
    )

  Where ``path/to/buildfile:targetname`` is the dependent target address.
  """

  @classmethod
  def parse(cls, spec, relative_to='', subproject_roots=None):
    """Parses an address from its serialized form.

    :param string spec: An address in string form <path>:<name>.
    :param string relative_to: For sibling specs, ie: ':another_in_same_build_family', interprets
                               the missing spec_path part as `relative_to`.
    :param list subproject_roots: Paths that correspond with embedded build roots
                                  under the current build root.
    :returns: A new address.
    :rtype: :class:`pants.base.address.Address`
    """
    spec_path, target_name = parse_spec(spec,
                                        relative_to=relative_to,
                                        subproject_roots=subproject_roots)
    return cls(spec_path, target_name)

  @classmethod
  def sanitize_path(cls, path):
    # A root or relative spec is OK
    if path == '':
      return path

    normpath = os.path.normpath(path)
    components = normpath.split(os.sep)
    if components[0] in ('.', '..') or normpath != path:
      raise InvalidSpecPath("Spec has un-normalized path part '{path}'".format(path=path))
    if components[-1].startswith('BUILD'):
      raise InvalidSpecPath('Spec path {path} has {trailing} as the last path part and BUILD is '
                            'reserved files'.format(path=path, trailing=components[-1]))
    if os.path.isabs(path):
      raise InvalidSpecPath('Spec has absolute path {path}; expected a path relative '
                            'to the build root.'.format(path=path))
    return normpath if normpath != '.' else ''

  @classmethod
  def check_target_name(cls, spec_path, name):
    if not name:
      raise InvalidTargetName('Spec {spec}:{name} has no name part'
                                 .format(spec=spec_path, name=name))

    banned_chars = BANNED_CHARS_IN_TARGET_NAME & set(name)

    if banned_chars:
      raise InvalidTargetName('banned chars found in target name',
                              '{banned_chars} not allowed in target name: {name}'
                              .format(banned_chars=banned_chars, name=name))

  def __init__(self, spec_path, target_name):
    """
    :param string spec_path: The path from the root of the repo to this Target.
    :param string target_name: The name of a target this Address refers to.
    """
    self._spec_path = self.sanitize_path(spec_path)
    self.check_target_name(spec_path, target_name)
    self._target_name = target_name
    self._hash = hash((self._spec_path, self._target_name))

  @property
  def spec_path(self):
    """
    :API: public
    """
    return self._spec_path

  @property
  def target_name(self):
    """
    :API: public
    """
    return self._target_name

  @property
  def spec(self):
    """The canonical string representation of the Address.

    Prepends '//' if the target is at the root, to disambiguate root-level targets
    from "relative" spec notation.

    :API: public
    """
    # TODO(pl): Maybe we should just always start with // for simplicity?
    return '{spec_path}:{target_name}'.format(spec_path=self._spec_path or '//',
                                              target_name=self._target_name)

  @property
  def path_safe_spec(self):
    """
    :API: public
    """
    return ('{safe_spec_path}.{target_name}'
            .format(safe_spec_path=self._spec_path.replace(os.sep, '.'),
                    target_name=self._target_name.replace(os.sep, '.')))

  @property
  def relative_spec(self):
    """
    :API: public
    """
    return ':{target_name}'.format(target_name=self._target_name)

  def reference(self, referencing_path=None):
    """How to reference this address in a BUILD file.

    :API: public
    """
    if referencing_path is not None and self._spec_path == referencing_path:
      return self.relative_spec
    elif os.path.basename(self._spec_path) != self._target_name:
      return self.spec
    else:
      return self._spec_path

  def __eq__(self, other):
    if not isinstance(other, Address):
      return False
    return (self._spec_path == other._spec_path and
            self._target_name == other._target_name)

  def __hash__(self):
    return self._hash

  def __ne__(self, other):
    return not self == other

  def __repr__(self):
    return self.spec

  def __lt__(self, other):
    return (self._spec_path, self._target_name) < (other._spec_path, other._target_name)


class BuildFileAddress(Address):
  """Represents the address of a type materialized from a BUILD file.

  :API: public
  """

  def __init__(self, build_file=None, target_name=None, rel_path=None):
    """
    :param build_file: The build file that contains the object this address points to.
    :type build_file: :class:`pants.base.build_file.BuildFile`
    :param string rel_path: The BUILD files' path, relative to the root_dir.
    :param string target_name: The name of the target within the BUILD file; defaults to the default
                               target, aka the name of the BUILD file parent dir.

    :API: public
    """
    rel_path = rel_path or build_file.relpath
    spec_path = os.path.dirname(rel_path)
    super(BuildFileAddress, self).__init__(spec_path=spec_path,
                                           target_name=target_name or os.path.basename(spec_path))
    self.rel_path = rel_path
    self._build_file = build_file

  def to_address(self):
    """Convert this BuildFileAddress to an Address."""
    return Address(spec_path=self.spec_path, target_name=self.target_name)

  @property
  @deprecated('1.5.0.dev0',
              hint_message='Use `BuildFileAddress.rel_path` to access the relative path to the '
                           'BUILD file for a target.')
  def build_file(self):
    """The build file that contains the object this address points to.

    :API: public

    :rtype: :class:`pants.base.build_file.BuildFile`
    """
    return self._build_file

  def __repr__(self):
    return ('BuildFileAddress({rel_path}, {target_name})'
            .format(rel_path=self.rel_path, target_name=self.target_name))
