# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re

from pants.base.deprecated import warn_or_error
from pants.base.hash_utils import stable_json_hash
from pants.base.payload import Payload
from pants.base.payload_field import PayloadField
from pants.base.validation import assert_list
from pants.build_graph.target import Target
from pants.util.memo import memoized_property
from pants.util.objects import datatype


# TODO: generalize this to a DatatypeSetField subclass in payload_field.py!
class ConanRequirementSetField(tuple, PayloadField):
  def _compute_fingerprint(self):
    return stable_json_hash(tuple(hash(req) for req in self))


class ConanRequirement(datatype(['pkg_spec', 'include_relpath', 'lib_relpath', ('lib_names', tuple)])):

  @classmethod
  def alias(cls):
    return 'conan_requirement'

  def __new__(cls, pkg_spec, include_relpath=None, lib_relpath=None, lib_names=None):
    """
    TODO: docstring! the reason for specifying these per-package is because they are a convention --
    see https://docs.conan.io/en/latest/using_packages/conanfile_txt.html#imports.
    """
    return super(ConanRequirement, cls).__new__(
      cls,
      pkg_spec,
      include_relpath=include_relpath or 'include',
      lib_relpath=lib_relpath or 'lib',
      lib_names=lib_names or ())

  def parse_conan_stdout_for_pkg_sha(self, stdout):
    # TODO(#6168): Add a JSON output mode in upstream Conan instead of parsing this.
    pkg_spec_pattern = re.compile(r'{}:([^\s]+)'.format(re.escape(self.pkg_spec)))
    return pkg_spec_pattern.search(stdout).group(1)

  @memoized_property
  def directory_path(self):
    """
    A helper method for converting Conan to package specifications to the data directory
    path that Conan creates for each package.

    Example package specification:
      "my_library/1.0.0@pants/stable"
    Example of the direcory path that Conan downloads pacakge data for this package to:
      "my_library/1.0.0/pants/stable"

    For more info on Conan package specifications, see:
      https://docs.conan.io/en/latest/introduction.html
    """
    return self.pkg_spec.replace('@', '/')


class ExternalNativeLibrary(Target):
  """A set of Conan package strings to be passed to the Conan package manager."""

  @classmethod
  def alias(cls):
    return 'external_native_library'

  class _DeprecatedStringPackage(Exception): pass

  def __init__(self, payload=None, packages=None, **kwargs):
    """
    :param packages: a list of Conan-style package strings

    Example:
      lzo/2.10@twitter/stable
    """
    payload = payload or Payload()

    try:
      assert_list(packages, key_arg='packages', expected_type=ConanRequirement,
                  raise_type=self._DeprecatedStringPackage)
    except self._DeprecatedStringPackage as e:
      warn_or_error('1.16.0.dev1',
                    'Raw strings as conan package descriptors',
                    hint='Use conan_requirement(...) instead! Error was: {}'.format(str(e)),
                    stacklevel=2)
      packages = [ConanRequirement(s) if not isinstance(s, ConanRequirement) else s
                  for s in packages]

    payload.add_fields({
      'packages': ConanRequirementSetField(packages),
    })
    super(ExternalNativeLibrary, self).__init__(payload=payload, **kwargs)

  @property
  def packages(self):
    return self.payload.packages

  # These are always going to be include/ and lib/ as we populate the constituent requirements there
  # in `NativeExternalLibraryFetch`, and we need to add these to the copied attributes for generated
  # targets in ._copy_target_attributes.
  @property
  def include_relpath(self):
    return 'include'

  @property
  def lib_relpath(self):
    return 'lib'

  @property
  def native_lib_names(self):
    lib_names = []
    for req in self.payload.packages:
      lib_names.extend(req.lib_names)
    return lib_names
