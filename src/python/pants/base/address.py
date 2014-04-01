# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.lang import Compatibility

from pants.base.build_file import BuildFile


class Address(object):
  """A target address.

  An address is a unique name representing a
  :class:`pants.base.target.Target`. Its composed of the
  :class:`pants.base.build_file.BuildFile` plus target name.

  While not their only use, a noteworthy use of addresses is specifying
  target dependencies. For example:

  ::

    some_target(name='mytarget',
      dependencies=[pants('path/to/buildfile:targetname')]
    )

  Where ``path/to/buildfile:targetname`` is the dependent target address.
  """

  @classmethod
  def parse(cls, root_dir, spec, is_relative=True):
    """Parses the given spec into an Address.

    An address spec can be one of:
    1.) the (relative) path of a BUILD file
    2.) the (relative) path of a directory containing a BUILD file child
    3.) either of 1 or 2 with a ':[target name]' suffix
    4.) a bare ':[target name]' indicating the BUILD file to use is the one in the current directory

    If the spec does not have a target name suffix the target name is taken to be the same name
    as the BUILD file's parent directory.  In this way the containing directory name
    becomes the 'default' target name for a BUILD file.

    If there is no BUILD file at the path pointed to, or if there is but the specified target name
    is not defined in the BUILD file, an IOError is raised.
    """

    if spec.startswith(':'):
      spec = '.' + spec
    parts = spec.split(':', 1)
    path = parts[0]
    if is_relative:
      path = os.path.relpath(os.path.abspath(path), root_dir)
    buildfile = BuildFile(root_dir, path)

    name = os.path.basename(os.path.dirname(buildfile.relpath)) if len(parts) == 1 else parts[1]
    return Address(buildfile, name)

  def __init__(self, buildfile, target_name):
    """
    :param BuildFile buildfile: A BuildFile defined in the repo.
    :param string target_name: The name of a target defined in buildfile.
    """
    assert isinstance(buildfile, BuildFile)
    assert isinstance(target_name, Compatibility.string)
    self.buildfile = buildfile
    self.target_name = target_name

  def reference(self, referencing_buildfile_path=None):
    """How to reference this address in a BUILD file."""
    dirname = os.path.dirname(self.buildfile.relpath)
    if referencing_buildfile_path and dirname == os.path.dirname(referencing_buildfile_path):
      return ':%s' % self.target_name
    elif os.path.basename(dirname) != self.target_name:
      return '%s:%s' % (dirname, self.target_name)
    else:
      return dirname

  def __eq__(self, other):
    result = other and (
      type(other) == Address) and (
      self.buildfile.canonical_relpath == other.buildfile.canonical_relpath) and (
      self.target_name == other.target_name)
    return result

  def __hash__(self):
    value = 17
    value *= 37 + hash(self.buildfile.canonical_relpath)
    value *= 37 + hash(self.target_name)
    return value

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "%s:%s" % (self.buildfile, self.target_name)
