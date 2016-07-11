# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import abstractproperty

from pants.engine.addressable import Exactly, addressable
from pants.engine.fs import PathGlobs
from pants.engine.objects import Locatable
from pants.engine.struct import Struct


class Sources(Struct, Locatable):
  """Represents a collection of source files.

  Note that because this does not extend `StructWithDeps`, subclasses that would like to have
  dependencies should mix-in StructWithDeps.
  """

  def __init__(self,
               name=None,
               files=None,
               globs=None,
               rglobs=None,
               zglobs=None,
               excludes=None,
               **kwargs):
    """
    :param string name: An optional name of this set of sources if the set is top-level for sharing.
    :param files: See fs.PathGlobs.
    :param globs: See fs.PathGlobs.
    :param rglobs: See fs.PathGlobs.
    :param zglobs: See fs.PathGlobs.
    :param excludes: A set of Sources to exclude from the files otherwise gathered here.
    :type excludes: :class:`Sources`
    """
    super(Sources, self).__init__(name=name, files=files, globs=globs, rglobs=rglobs, zglobs=zglobs,
                                  **kwargs)
    if files and self.extensions:
      for f in files:
        if not self._accept_file(f):
          # TODO: TargetDefinitionError or similar
          raise ValueError('Path `{}` selected by {} is not a {} file.'.format(
            f, self, self.extensions))
    self.excludes = excludes

  def _accept_file(self, f):
    """Returns true if the given file's extension matches this Sources type."""
    _, ext = os.path.splitext(f)
    return ext in self.extensions

  @property
  def path_globs(self):
    """Creates a `PathGlobs` object for the paths matched by these Sources.

    This field may be projected to request the content of the files for this Sources object.
    """
    return PathGlobs.create(self.spec_path,
                            files=self.files,
                            globs=self.globs,
                            rglobs=self.rglobs,
                            zglobs=self.zglobs)

  @abstractproperty
  def extensions(self):
    """A collection of file extensions collected by this Sources instance.

    An empty collection indicates that any extension will be accepted.
    """

  @property
  def excludes(self):
    """The sources to exclude.

    :rtype: :class:`Sources`
    """

# Since Sources.excludes is recursive on the Sources type, we need to post-class-definition
# re-define excludes in this way.
Sources.excludes = addressable(Exactly(Sources))(Sources.excludes)
