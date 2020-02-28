# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.util.memo import memoized_property


class ResolvedJar:
    """Represents an artifact resolved from the dependency resolution process."""

    def __init__(self, coordinate, cache_path, pants_path=None, directory_digest=None):
        """
        :param coordinate: Coordinate representing this resolved jar.
        :type coordinate: :class:`M2Coordinate`
        :param string cache_path: Path to the artifact in the ivy cache
        :param string pants_path: Path to the symlink for the artifact in the pants work directory.
        :param Digest directory_digest: Digest of the artifact.
        """
        self.coordinate = coordinate
        self.cache_path = cache_path
        self.pants_path = pants_path
        self.directory_digest = directory_digest

        self._id = (coordinate, cache_path, pants_path, directory_digest)

    def __eq__(self, other):
        return isinstance(other, ResolvedJar) and self._id == other._id

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self._id)

    def __repr__(self):
        return (
            "ResolvedJar(coordinate={!r}, cache_path={!r}, pants_path={!r}, "
            "directory_digest={!r})".format(*self._id)
        )


class M2Coordinate(object):
    """Represents a fully qualified name of an artifact.

    :API: public
    """

    def __init__(self, org, name, rev=None, classifier=None, ext=None):
        """
        :param string org: The maven dependency `groupId`.
        :param string name: The maven dependency `artifactId`.
        :param string rev: The maven dependency `version`.
        :param string classifier: The maven dependency `classifier`.
        :param string ext: There is no direct maven parallel, but the maven `packaging` value of the
                           depended-on artifact for simple cases, and in more complex cases the
                           extension of the artifact.  For example, 'bundle' packaging implies an
                           extension of 'jar'.  Defaults to 'jar'.
        """
        self.org = org
        self.name = name
        self.rev = rev
        self.classifier = classifier
        self._ext = ext

        self._id = (self.org, self.name, self.rev, self.classifier, self.ext)

    @property
    def ext(self):
        return self._ext or "jar"

    @classmethod
    def create(cls, jar):
        """Creates an actual M2Coordinate from the given M2Coordinate-like object (eg a
        JarDependency).

        :API: public

        :param JarDependency jar: the input coordinate.
        :return: A new M2Coordinate, unless the input is already an M2Coordinate in which case it just
          returns the input unchanged.
        :rtype: M2Coordinate
        """
        if isinstance(jar, cls):
            return jar
        return cls(org=jar.org, name=jar.name, rev=jar.rev, classifier=jar.classifier, ext=jar.ext)

    @classmethod
    def unversioned(cls, coord):
        """The coordinate without the version.

        :param M2Coordinate coord: an M2Coordinate or JarDependency.
        :return: the coordinate without the version.
        :rtype: M2Coordinate
        """
        coord = cls.create(coord)
        if coord.rev is None:
            return coord
        return M2Coordinate(
            org=coord.org, name=coord.name, classifier=coord.classifier, ext=coord.ext
        )

    @memoized_property
    def artifact_filename(self):
        """Returns the canonical maven-style filename for an artifact pointed at by this coordinate.

        :API: public

        :rtype: string
        """

        def maybe_compenent(component):
            return "-{}".format(component) if component else ""

        return "{org}-{name}{rev}{classifier}.{ext}".format(
            org=self.org,
            name=self.name,
            rev=maybe_compenent(self.rev),
            classifier=maybe_compenent(self.classifier),
            ext=self.ext,
        )

    @classmethod
    def from_string(cls, string_coord):
        packaging = None
        classifier = None
        ct = string_coord.count(":")
        if ct == 2:
            org, name, rev = string_coord.split(":")
        elif ct == 3:
            org, name, packaging, rev = string_coord.split(":")
        elif ct == 4:
            org, name, packaging, classifier, rev = string_coord.split(":")
        rev = rev or None
        return M2Coordinate(org=org, name=name, rev=rev, ext=packaging, classifier=classifier)

    @property
    def simple_coord(self):
        """A simple version of coordinate representation with org:name:version without classifier or
        ext.

        :return: org:name:version
        """
        return "{}:{}:{}".format(self.org, self.name, self.rev)

    def __eq__(self, other):
        return isinstance(other, M2Coordinate) and self._id == other._id

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self._id)

    def __str__(self):
        # Follows https://maven.apache.org/pom.html#Maven_Coordinates,
        # with the exception that if rev is missing, it adds an extra ':' at the end.
        # for example org=a, name=b, type_=jar -> a:b:jar:
        if self.classifier:
            components = (self.org, self.name, self.ext or "jar", self.classifier, self.rev or "")
        elif self.ext and self.ext != "jar":
            components = (self.org, self.name, self.ext, self.rev or "")
        else:
            components = (self.org, self.name, self.rev or "")

        return ":".join((x or "") for x in components)

    def __repr__(self):
        return "M2Coordinate(org={!r}, name={!r}, rev={!r}, classifier={!r}, ext={!r})".format(
            *self._id
        )

    def copy(self, **replacements):
        """Returns a clone of this M2Coordinate with the given replacements kwargs overlaid."""
        cls = type(self)
        kwargs = {
            "org": self.org,
            "name": self.name,
            "ext": self.ext,
            "classifier": self.classifier,
            "rev": self.rev,
        }
        for key, val in replacements.items():
            kwargs[key] = val
        return cls(**kwargs)
