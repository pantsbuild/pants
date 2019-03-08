# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from twitter.common.collections import maybe_list

from pants.backend.python.targets.import_wheels_mixin import ImportWheelsMixin
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


logger = logging.getLogger(__name__)


class UnpackedWheels(ImportWheelsMixin, Target):
  """A set of sources extracted from JAR files.

  NB: Currently, wheels are always resolved for the 'current' platform.

  :API: public
  """

  imported_target_kwargs_field = 'libraries'
  imported_target_payload_field = 'library_specs'

  @classmethod
  def alias(cls):
    return 'unpacked_whls'

  class ExpectedLibrariesError(Exception):
    """Thrown when the target has no libraries defined."""
    pass

  # TODO: consider introducing some form of source roots instead of the manual `within_data_subdir`
  # kwarg!
  def __init__(self, module_name, libraries=None, include_patterns=None, exclude_patterns=None,
               compatibility=None, within_data_subdir=None, payload=None, **kwargs):
    """
    :param str module_name: The name of the specific python module containing headers and/or
                            libraries to extract (e.g. 'tensorflow').
    :param list libraries: addresses of python_requirement_library targets that specify the wheels
                           you want to unpack
    :param list include_patterns: fileset patterns to include from the archive
    :param list exclude_patterns: fileset patterns to exclude from the archive. Exclude patterns
      are processed before include_patterns.
    :param compatibility: Python interpreter constraints used to create the pex for the requirement
                          target. If unset, the default interpreter constraints are used. This
                          argument is unnecessary unless the native code depends on libpython.
    :param str within_data_subdir: If provided, descend into '<name>-<version>.data/<subdir>' when
                                   matching `include_patterns`. For python wheels which declare any
                                   non-code data, this is usually needed to extract that without
                                   manually specifying the relative path, including the package
                                   version. For example, when `data_files` is used in a setup.py,
                                   `within_data_subdir='data'` will allow specifying
                                   `include_patterns` matching exactly what is specified in the
                                   setup.py.
    """
    payload = payload or Payload()
    payload.add_fields({
      'library_specs': PrimitiveField(libraries or ()),
      'module_name': PrimitiveField(module_name),
      'include_patterns' : PrimitiveField(include_patterns or ()),
      'exclude_patterns' : PrimitiveField(exclude_patterns or ()),
      'compatibility': PrimitiveField(maybe_list(compatibility or ())),
      'within_data_subdir': PrimitiveField(within_data_subdir),
      # TODO: consider supporting transitive deps like UnpackedJars!
      # TODO: consider supporting `platforms` as in PythonBinary!
    })
    super(UnpackedWheels, self).__init__(payload=payload, **kwargs)

    if not libraries:
      raise self.ExpectedLibrariesError('Expected non-empty libraries attribute for {spec}'
                                        .format(spec=self.address.spec))

  @property
  def module_name(self):
    return self.payload.module_name

  @property
  def compatibility(self):
    return self.payload.compatibility

  @property
  def within_data_subdir(self):
    return self.payload.within_data_subdir
