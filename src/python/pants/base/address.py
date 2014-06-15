# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.lang import AbstractClass



def parse_spec(spec, relative_to=''):
  """Parses a target address spec and returns the path from the root of the repo to this Target
  and Target name.
  :param string spec: target address spec
  For Example
  ::
    some_target(name='mytarget',
      dependencies=['path/to/buildfile:targetname']
    )

  Where  ``path/to/buildfile:targetname`` is the dependent target address spec

  In case, the target name is empty it returns the last component of the path as target name.
  ::
    spec_path, target_name = parse_spec('path/to/buildfile/foo')

  Will return spec_path as 'path/to/buildfile/foo' and target_name as 'foo'
  """
  spec_parts = spec.rsplit(':', 1)
  if len(spec_parts) == 1:
    spec_path = os.path.normpath(spec_parts[0])
    assert spec_path, (
      'Attempted to parse a bad spec string {spec}: empty spec string'
      .format(spec=spec)
    )
    target_name = os.path.basename(spec_path)
    return spec_path, target_name

  spec_path, target_name = spec_parts
  if not spec_path:
    spec_path = relative_to
  return spec_path, target_name


class Address(AbstractClass):
  """A target address.

  An address is a unique name representing a
  :class:`pants.base.target.Target`. It's composed of the
  path from the root of the repo to the Target plus the target name.

  While not their only use, a noteworthy use of addresses is specifying
  target dependencies. For example:

  ::

    some_target(name='mytarget',
      dependencies=['path/to/buildfile:targetname']
    )

  Where ``path/to/buildfile:targetname`` is the dependent target address.
  """

  def __init__(self, spec_path, target_name):
    """
    :param string spec_path: The path from the root of the repo to this Target.
    :param string target_name: The name of a target this Address refers to.
    """
    # TODO(John Sirois): AbstractClass / Interface should probably have this feature built in.
    if type(self) == Address:
      raise TypeError('Cannot instantiate abstract class Address')
    norm_path = os.path.normpath(spec_path)
    self.spec_path = norm_path if norm_path != '.' else ''
    self.target_name = target_name

  @property
  def spec(self):
    return '{spec_path}:{target_name}'.format(spec_path=self.spec_path,
                                              target_name=self.target_name)

  @property
  def path_safe_spec(self):
    return ('{safe_spec_path}.{target_name}'
            .format(safe_spec_path=self.spec_path.replace(os.sep, '.'),
                    target_name=self.target_name))

  @property
  def relative_spec(self):
    return ':{target_name}'.format(target_name=self.target_name)

  @property
  def is_synthetic(self):
    return False

  def reference(self, referencing_path=None):
    """How to reference this address in a BUILD file."""
    if referencing_path and self.spec_path == referencing_path:
      return self.relative_spec
    elif os.path.basename(self.spec_path) != self.target_name:
      return self.spec
    else:
      return self.spec_path

  def __eq__(self, other):
    return (other and
            self.spec_path == other.spec_path and
            self.target_name == other.target_name)

  def __hash__(self):
    return hash((self.spec_path, self.target_name))

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return self.spec

  def __lt__(self, other):
    return (self.spec_path, self.target_name) < (other.spec_path, other.target_name)


class BuildFileAddress(Address):
  def __init__(self, build_file, target_name=None):
    self.build_file = build_file
    spec_path = os.path.dirname(build_file.relpath)
    default_target_name = os.path.basename(spec_path)
    super(BuildFileAddress, self).__init__(spec_path=spec_path,
                                           target_name=target_name or default_target_name)

  @property
  def build_file_spec(self):
    return ("{build_file}:{target_name}"
            .format(build_file=self.build_file,
                    target_name=self.target_name))

  def __repr__(self):
    return ("BuildFileAddress({build_file}, {target_name})"
            .format(build_file=self.build_file,
                    target_name=self.target_name))


class SyntheticAddress(Address):
  @classmethod
  def parse(cls, spec, relative_to=''):
    spec_path, target_name = parse_spec(spec, relative_to=relative_to)
    return cls(spec_path, target_name)

  def __repr__(self):
    return "SyntheticAddress({spec})".format(spec=self.spec)

  @property
  def is_synthetic(self):
    return True
