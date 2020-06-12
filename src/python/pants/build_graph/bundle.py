# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from collections import OrderedDict, namedtuple
from hashlib import sha1

from pants.base.build_environment import get_buildroot
from pants.base.payload_field import PayloadField, combine_hashes
from pants.util.collections import ensure_str_list
from pants.util.dirutil import fast_relpath
from pants.util.memo import memoized_property


class Bundle:
    """A set of files to include in an application bundle.

    To learn about application bundles, see
    `bundles <JVMProjects.html#jvm-bundles>`_.
    Looking for Java-style resources accessible via the ``Class.getResource`` API?
    Those are `resources <build_dictionary.html#resources>`_.

    Files added to the bundle will be included when bundling an application target.
    By default relative paths are preserved. For example, to include ``config``
    and ``scripts`` directories: ::

      bundles=[
        bundle(fileset=[config/**/*', 'scripts/**/*', 'my.cfg']),
      ]

    To include files relative to some path component use the ``relative_to`` parameter.
    The following places the contents of ``common/config`` in a  ``config`` directory
    in the bundle. ::

      bundles=[
        bundle(relative_to='common', fileset=['common/config/*'])
      ]
    """

    def __init__(self, parse_context):
        self._parse_context = parse_context

    def __call__(self, rel_path=None, mapper=None, relative_to=None, fileset=None):
        """
        :param rel_path: Base path of the "source" file paths. By default, path of the
          BUILD file. Useful for assets that don't live in the source code repo.
        :param mapper: Function that takes a path string and returns a path string. Takes a path in
          the source tree, returns a path to use in the resulting bundle. By default, an identity
          mapper.
        :param string relative_to: Set up a simple mapping from source path to bundle path.
        :param fileset: The set of files to include in the bundle.  A string filename or a list of
          filenames/globs.
          E.g., ``relative_to='common'`` removes that prefix from all files in the application bundle.
        """

        if fileset is None:
            raise ValueError(
                "In {}:\n  Bare bundle() declarations without a `fileset=` parameter "
                "are no longer supported.".format(self._parse_context.rel_path)
            )

        if mapper and relative_to:
            raise ValueError("Must specify exactly one of 'mapper' or 'relative_to'")

        # A fileset is either a string or a list of file paths. All globs are expected to already
        # have been expanded.
        fileset = ensure_str_list(fileset, allow_single_str=True)
        assert all("*" not in fp for fp in fileset), (
            "All globs should have already been hydrated for the `bundle(fileset=)` field. "
            f"Given the fileset: {fileset}"
        )

        real_rel_path = rel_path or self._parse_context.rel_path

        if relative_to:
            base = os.path.join(get_buildroot(), real_rel_path, relative_to)
            mapper = RelativeToMapper(base)
        else:
            mapper = mapper or RelativeToMapper(os.path.join(get_buildroot(), real_rel_path))

        return BundleProps(real_rel_path, mapper, fileset)

    def create_bundle_props(self, bundle):
        rel_path = getattr(bundle, "rel_path", None)
        mapper = getattr(bundle, "mapper", None)
        relative_to = getattr(bundle, "relative_to", None)
        fileset = getattr(bundle, "fileset", None)
        return self(rel_path, mapper, relative_to, fileset)


class RelativeToMapper:
    """A mapper that maps filesystem paths specified relative to a base directory."""

    def __init__(self, base):
        """The base directory paths should be mapped from."""
        self.base = base

    def __call__(self, path):
        return os.path.relpath(path, self.base)

    def __repr__(self):
        return "IdentityMapper({})".format(self.base)

    def __hash__(self):
        return hash(self.base)


class BundleProps(namedtuple("_BundleProps", ["rel_path", "mapper", "fileset"])):
    def _filemap(self, abs_path):
        filemap = OrderedDict()
        for path in self.fileset:
            if abs_path:
                if not os.path.isabs(path):
                    path = os.path.join(get_buildroot(), self.rel_path, path)
            else:
                if os.path.isabs(path):
                    path = fast_relpath(path, get_buildroot())
                else:
                    path = os.path.join(self.rel_path, path)
            filemap[path] = self.mapper(path)
        return filemap

    @memoized_property
    def filemap(self):
        return self._filemap(abs_path=True)

    @memoized_property
    def relative_filemap(self):
        return self._filemap(abs_path=False)

    def __hash__(self):
        # Leave out fileset from hash calculation since it may not be hashable.
        return hash((self.rel_path, self.mapper))


class BundleField(tuple, PayloadField):
    """A tuple subclass that mixes in PayloadField.

    Must be initialized with an iterable of Bundle instances.
    """

    @staticmethod
    def _hash_bundle(bundle):
        hasher = sha1()
        hasher.update(bundle.rel_path.encode())
        for abs_path in sorted(bundle.filemap.keys()):
            buildroot_relative_path = os.path.relpath(abs_path, get_buildroot()).encode()
            hasher.update(buildroot_relative_path)
            hasher.update(bundle.filemap[abs_path].encode())
            if os.path.isfile(abs_path):
                # Update with any additional string to differentiate empty file with non-existing file.
                hasher.update(b"e")
                with open(abs_path, "rb") as f:
                    hasher.update(f.read())
        return hasher.hexdigest()

    def _compute_fingerprint(self):
        return combine_hashes(list(map(BundleField._hash_bundle, self)))
