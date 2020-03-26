# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from pants.base.hash_utils import stable_json_sha1
from pants.base.payload import Payload
from pants.base.payload_field import PayloadField
from pants.base.validation import assert_list
from pants.build_graph.target import Target
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init


# TODO: generalize this to a DatatypeSetField subclass in payload_field.py!
class ConanRequirementSetField(tuple, PayloadField):
    def _compute_fingerprint(self):
        return stable_json_sha1(tuple(hash(req) for req in self))


@frozen_after_init
@dataclass(unsafe_hash=True)
class ConanRequirement:
    """A specification for a conan package to be resolved against a remote repository.

    Example `pkg_spec`: 'lzo/2.10@twitter/stable'

    The include and lib dirs default to 'include/' and 'lib/', but as this is a convention, they can
    be overridden for the specific package to be resolved. See
    https://docs.conan.io/en/latest/using_packages/conanfile_txt.html#imports for more info.
    """

    pkg_spec: str
    include_relpath: str
    lib_relpath: str
    lib_names: Tuple[str, ...]

    def __init__(
        self,
        pkg_spec: str,
        include_relpath: Optional[str] = None,
        lib_relpath: Optional[str] = None,
        lib_names: Optional[Sequence[str]] = None,
    ) -> None:
        """
        :param pkg_spec: A string specifying a conan package at a specific version, as per
                         https://docs.conan.io/en/latest/using_packages/conanfile_txt.html#requires
        :param include_relpath: The relative path from the package root directory to where C/C++
                                headers are located.
        :param lib_relpath: The relative path from the package root directory to where native
                            libraries are located.
        :param lib_names: Strings containing the libraries to add to the linker command
                          line. Collected into the `native_lib_names` field of a
                          `packaged_native_library()` target.
        """
        self.pkg_spec = pkg_spec
        self.include_relpath = include_relpath or "include"
        self.lib_relpath = lib_relpath or "lib"
        self.lib_names = tuple(lib_names or ())

    @classmethod
    def alias(cls):
        return "conan_requirement"

    def parse_conan_stdout_for_pkg_sha(self, stdout):
        # TODO(#6168): Add a JSON output mode in upstream Conan instead of parsing this.
        pkg_spec_pattern = re.compile(r"{}:([^\s]+)".format(re.escape(self.pkg_spec)))
        return pkg_spec_pattern.search(stdout).group(1)

    @memoized_property
    def directory_path(self):
        """A helper method for converting Conan to package specifications to the data directory path
        that Conan creates for each package.

        Example package specification:
          "my_library/1.0.0@pants/stable"
        Example of the direcory path that Conan downloads package data for this package to:
          "my_library/1.0.0/pants/stable"

        For more info on Conan package specifications, see:
          https://docs.conan.io/en/latest/introduction.html
        """
        return self.pkg_spec.replace("@", "/")


class ExternalNativeLibrary(Target):
    """A set of Conan package strings to be passed to the Conan package manager."""

    @classmethod
    def alias(cls):
        return "external_native_library"

    class _DeprecatedStringPackage(Exception):
        pass

    def __init__(self, payload=None, packages=None, **kwargs):
        """
        :param list packages: the `ConanRequirement`s to resolve into a `packaged_native_library()` target.
        """
        payload = payload or Payload()

        assert_list(
            packages,
            key_arg="packages",
            expected_type=ConanRequirement,
            raise_type=self._DeprecatedStringPackage,
        )

        payload.add_fields({"packages": ConanRequirementSetField(packages)})
        super().__init__(payload=payload, **kwargs)

    @property
    def packages(self):
        return self.payload.packages

    # NB: These are always going to be include/ and lib/ as we populate the constituent requirements
    # there in `ConanFetch`, and we need to add these to the copied attributes for
    # generated targets in ._copy_target_attributes. These need to have the same names as in
    # `packaged_native_library()` so that the methods in the `SimpleCodegenTask` superclass can copy
    # the attributes over.
    @property
    def include_relpath(self):
        return "include"

    @property
    def lib_relpath(self):
        return "lib"

    @property
    def native_lib_names(self):
        lib_names = []
        for req in self.payload.packages:
            lib_names.extend(req.lib_names)
        return lib_names
