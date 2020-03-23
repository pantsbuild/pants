# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os


class ClasspathEntry:
    """Represents a java classpath entry.

    :API: public
    """

    def __init__(self, path, directory_digest=None):
        self._path = path
        self._directory_digest = directory_digest

    @property
    def path(self):
        """Returns the pants internal path of this classpath entry.

        Suitable for use in constructing classpaths for pants executions and pants generated artifacts.

        :API: public

        :rtype: string
        """
        return self._path

    def hydrate_missing_directory_digest(self, directory_digest):
        assert os.path.exists(
            self.path
        ), f"Classpath entry {self} with digest to be mutated should point to an existing file or directory!"
        assert self.directory_digest is None or self._directory_digest == directory_digest, (
            f"Classpath entry {self} with digest {self.directory_digest} to be mutated is expected to be None "
            f"or the same as the incoming digest {directory_digest}!"
        )
        self._directory_digest = directory_digest

    @property
    def directory_digest(self):
        """Returns the directory digest which contains this file. May be None.

        This API is experimental, and subject to change.

        :rtype: pants.engine.fs.Digest
        """
        return self._directory_digest

    def is_excluded_by(self, excludes):
        """Returns `True` if this classpath entry should be excluded given the `excludes` in play.

        :param excludes: The excludes to check this classpath entry against.
        :type excludes: list of :class:`pants.backend.jvm.targets.exclude.Exclude`
        :rtype: bool
        """
        return False

    def __hash__(self):
        return hash((self.path, self.directory_digest))

    def __eq__(self, other):
        return (
            isinstance(other, ClasspathEntry)
            and self.path == other.path
            and self.directory_digest == other.directory_digest
        )

    def __ne__(self, other):
        return not self == other

    def __repr__(self):
        return "ClasspathEntry(path={!r}, directory_digest={!r})".format(
            self.path, self.directory_digest,
        )

    @classmethod
    def is_artifact_classpath_entry(cls, classpath_entry):
        """
    :API: public
    """
        return isinstance(classpath_entry, ArtifactClasspathEntry)

    @classmethod
    def is_internal_classpath_entry(cls, classpath_entry):
        """
    :API: public
    """
        return not cls.is_artifact_classpath_entry(classpath_entry)


class ArtifactClasspathEntry(ClasspathEntry):
    """Represents a resolved third party classpath entry.

    :API: public
    """

    def __init__(self, path, coordinate, cache_path, directory_digest=None):
        super().__init__(path, directory_digest)
        self._coordinate = coordinate
        self._cache_path = cache_path

    @property
    def coordinate(self):
        """Returns the maven coordinate that used to resolve this classpath entry's artifact.

        :rtype: :class:`pants.java.jar.M2Coordinate`
        """
        return self._coordinate

    @property
    def cache_path(self):
        """Returns the external cache path of this classpath entry.

        For example, the `~/.m2/repository` or `~/.ivy2/cache` location of the resolved artifact for
        maven and ivy resolvers respectively.

        Suitable for use in constructing classpaths for external tools that should not be subject to
        potential volatility in pants own internal caches.

        :API: public

        :rtype: string
        """
        return self._cache_path

    def is_excluded_by(self, excludes):
        return any(_matches_exclude(self.coordinate, exclude) for exclude in excludes)

    def __hash__(self):
        return hash((self.path, self.coordinate, self.cache_path))

    def __eq__(self, other):
        return (
            isinstance(other, ArtifactClasspathEntry)
            and self.path == other.path
            and self.coordinate == other.coordinate
            and self.cache_path == other.cache_path
            and self.directory_digest == other.directory_digest
        )

    def __ne__(self, other):
        return not self == other

    def __repr__(self):
        return "ArtifactClasspathEntry(path={!r}, coordinate={!r}, cache_path={!r}, directory_digest={!r})".format(
            self.path, self.coordinate, self.cache_path, self.directory_digest
        )


def _matches_exclude(coordinate, exclude):
    if not coordinate.org == exclude.org:
        return False

    if not exclude.name:
        return True
    if coordinate.name == exclude.name:
        return True
    return False
