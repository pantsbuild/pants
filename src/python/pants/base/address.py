# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import namedtuple

from pants.util.meta import AbstractClass


def parse_spec(spec, relative_to=None):
  """Parses a target address spec and returns the path from the root of the repo to this Target
  and Target name.

  :param string spec: Target address spec.
  :param string relative_to: path to use for sibling specs, ie: ':another_in_same_build_family',
    interprets the missing spec_path part as `relative_to`.

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
    return ref.lstrip('//')

  def check_path(path):
    # A root or relative spec is OK
    if path == '':
      return

    normpath = os.path.normpath(path)
    components = normpath.split(os.sep)
    if components[0] in ('.', '..') or normpath != path:
      raise ValueError('Spec {spec} has un-normalized path '
                       'part {path}'.format(spec=spec, path=path))
    if components[-1].startswith('BUILD'):
      raise ValueError('Spec {spec} has {trailing} as the last path part and BUILD is '
                       'reserved files'.format(spec=spec, trailing=components[-1]))

  def check_target_name(name):
    if not name:
      raise ValueError('Spec {spec} has no name part'.format(spec=spec))

  spec_parts = spec.rsplit(':', 1)
  if len(spec_parts) == 1:
    spec_path = normalize_absolute_refs(spec_parts[0])
    target_name = os.path.basename(spec_path)
  else:
    spec_path, target_name = spec_parts
    if not spec_path and relative_to:
      spec_path = relative_to
    spec_path = normalize_absolute_refs(spec_path)

  check_path(spec_path)
  check_target_name(target_name)
  return spec_path, target_name


class Addresses(namedtuple('Addresses', ['addresses', 'rel_path'])):
  """ Used as a sentinel type for identifying a list of string specs.

  addresses: list of string specs
  rel_path: addresses might be relative specs, so they need to be interpreted
  relative to the path of the BUILD file they were declared in.
  """


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
  def parse(cls, spec, relative_to=''):
    """Parses an address from its serialized form.

    :param string spec: An address in string form <path>:<name>.
    :param string relative_to: For sibling specs, ie: ':another_in_same_build_family', interprets
                               the missing spec_path part as `relative_to`.
    :returns: A new address.
    :rtype: :class:`pants.base.address.Address`
    """
    spec_path, target_name = parse_spec(spec, relative_to=relative_to)
    return cls(spec_path, target_name)

  def __init__(self, spec_path, target_name):
    """
    :param string spec_path: The path from the root of the repo to this Target.
    :param string target_name: The name of a target this Address refers to.
    """
    norm_path = os.path.normpath(spec_path)
    self._spec_path = norm_path if norm_path != '.' else ''
    self._target_name = target_name

  @property
  def spec_path(self):
    return self._spec_path

  @property
  def target_name(self):
    return self._target_name

  @property
  def spec(self):
    return '{spec_path}:{target_name}'.format(spec_path=self._spec_path,
                                              target_name=self._target_name)

  @property
  def path_safe_spec(self):
    return ('{safe_spec_path}.{target_name}'
            .format(safe_spec_path=self._spec_path.replace(os.sep, '.'),
                    target_name=self._target_name.replace(os.sep, '.')))

  @property
  def relative_spec(self):
    return ':{target_name}'.format(target_name=self._target_name)

  def reference(self, referencing_path=None):
    """How to reference this address in a BUILD file."""
    if referencing_path and self._spec_path == referencing_path:
      return self.relative_spec
    elif os.path.basename(self._spec_path) != self._target_name:
      return self.spec
    else:
      return self._spec_path

  def __eq__(self, other):
    return (other and
            self._spec_path == other._spec_path and
            self._target_name == other._target_name)

  _hash = None

  def __hash__(self):
    if self._hash is None:
      self._hash = hash((self._spec_path, self._target_name))
    return self._hash

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return self.spec

  def __lt__(self, other):
    return (self._spec_path, self._target_name) < (other._spec_path, other._target_name)


class BuildFileAddress(Address):
  """Represents the address of a type materialized from a BUILD file."""

  def __init__(self, build_file, target_name=None):
    """
    :param build_file: The build file that contains the object this address points to.
    :type build_file: :class:`pants.base.build_file.BuildFile`
    :param string target_name: The name of the target within the BUILD file; defaults to the default
                               target, aka the name of the BUILD file parent dir.
    """
    spec_path = os.path.dirname(build_file.relpath)
    super(BuildFileAddress, self).__init__(spec_path=spec_path,
                                           target_name=target_name or os.path.basename(spec_path))
    self._build_file = build_file

  @property
  def build_file(self):
    """The build file that contains the object this address points to.

    :rtype: :class:`pants.base.build_file.BuildFile`
    """
    return self._build_file

  def __repr__(self):
    return ('BuildFileAddress({build_file}, {target_name})'
            .format(build_file=self.build_file, target_name=self.target_name))
