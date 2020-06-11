# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.bundle import BundleField
from pants.build_graph.target import Target
from pants.fs import archive as Archive
from pants.util.dirutil import fast_relpath


class DirectoryReMapper:
    """A mapper that maps files relative to a base directory into a destination directory."""

    class NonexistentBaseError(Exception):
        pass

    def __init__(self, base, dest):
        """The base directory files should be mapped from, and the dest they should be mapped to.

        :param string base: the relative path to get_buildroot()
        :param string dest: the dest path in the bundle
        """
        self.base = os.path.abspath(os.path.join(get_buildroot(), base))
        if not os.path.isdir(self.base):
            raise DirectoryReMapper.NonexistentBaseError(
                "Could not find a directory to bundle relative to {0}".format(self.base)
            )
        self.dest = dest

    def __call__(self, path):
        return os.path.join(self.dest, os.path.relpath(path, self.base))

    def __repr__(self):
        return "DirectoryReMapper({0}, {1})".format(self.base, self.dest)


class AppBase(Target):
    """A base class for deployable application targets.

    Invoking the ``bundle`` goal on one of these targets creates a
    self-contained artifact suitable for deployment on some other machine.
    The artifact contains the executable, its dependencies, and
    extra files like config files, startup scripts, etc.

    :API: public
    """

    class InvalidArchiveType(Exception):
        """Raised when archive type defined in Target is invalid."""

    def __init__(
        self,
        name=None,
        payload=None,
        binary=None,
        bundles=None,
        basename=None,
        archive=None,
        **kwargs,
    ):
        """
        :param string binary: Target spec of the ``jvm_binary`` or the ``python_binary``
          that contains the app main.
        :param bundles: One or more ``bundle``\\s
          describing "extra files" that should be included with this app
          (e.g.: config files, startup scripts).
        :param string basename: Name of this application, if different from the
          ``name``. Optionally pants uses this in the ``bundle`` goal to name the distribution
          artifact.  Note this is unsafe because of the possible conflict when multiple bundles
          are built.
        :param string archive: Create an archive of this type from the bundle.
        """
        if name == basename:
            raise TargetDefinitionException(self, "basename must not equal name.")

        payload = payload or Payload()
        payload.add_fields(
            {
                "basename": PrimitiveField(basename or name),
                "binary": PrimitiveField(binary),
                "bundles": BundleField(bundles or []),
                "archive": PrimitiveField(archive),
            }
        )
        if payload.archive and payload.archive not in Archive.TYPE_NAMES:
            raise self.InvalidArchiveType(
                'Given archive type "{}" is invalid, choose from {}.'.format(
                    payload.archive, list(Archive.TYPE_NAMES)
                )
            )
        super().__init__(name=name, payload=payload, **kwargs)

    def globs_relative_to_buildroot(self):
        buildroot = get_buildroot()
        globs = []
        for bundle in self.bundles:
            fileset = bundle.fileset
            if fileset is None:
                continue
            globs += [fast_relpath(f, buildroot) for f in bundle.filemap.keys()]
        super_globs = super().globs_relative_to_buildroot()
        if super_globs:
            globs += super_globs["globs"]
        return {"globs": globs}

    @classmethod
    def binary_target_type(cls):
        raise NotImplementedError("Must implement in subclass (e.g.: `return PythonBinary`)")

    @classmethod
    def compute_dependency_address_specs(cls, kwargs=None, payload=None):
        for address_spec in super().compute_dependency_address_specs(kwargs, payload):
            yield address_spec

        target_representation = kwargs or payload.as_dict()
        binary = target_representation.get("binary")
        if binary:
            yield binary

    @property
    def bundles(self):
        return self.payload.bundles

    @property
    def binary(self):
        """Returns the binary this target references."""
        dependencies = self.dependencies
        if len(dependencies) != 1:
            raise TargetDefinitionException(
                self,
                "An app must define exactly one binary "
                "dependency, have: {}".format(dependencies),
            )
        binary = dependencies[0]
        if not isinstance(binary, self.binary_target_type()):
            raise TargetDefinitionException(
                self,
                "Expected binary dependency to be a {} "
                "target, found {}".format(self.binary_target_type(), binary),
            )
        return binary
