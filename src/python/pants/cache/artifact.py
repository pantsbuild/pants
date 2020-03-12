# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil

from pants.util.contextutil import open_tar
from pants.util.dirutil import safe_mkdir, safe_mkdir_for, safe_walk


class ArtifactError(Exception):
    pass


class Artifact:
    """Represents a set of files in an artifact."""

    def __init__(self, artifact_root):
        # All files must be under this root.
        self._artifact_root = artifact_root

        # The files known to be in this artifact, relative to artifact_root.
        self._relpaths = set()

    def exists(self):
        """:returns True if the artifact is available for extraction."""
        raise NotImplementedError()

    def get_paths(self):
        for relpath in self._relpaths:
            yield os.path.join(self._artifact_root, relpath)

    def override_paths(self, paths):  # Use with care.
        self._relpaths = {os.path.relpath(path, self._artifact_root) for path in paths}

    def collect(self, paths):
        """Collect the paths (which must be under artifact root) into this artifact."""
        raise NotImplementedError()

    def extract(self):
        """Extract the files in this artifact to their locations under artifact root."""
        raise NotImplementedError()


class DirectoryArtifact(Artifact):
    """An artifact stored as loose files under a directory."""

    def __init__(self, artifact_root, directory):
        super().__init__(artifact_root)
        self._directory = directory

    def exists(self):
        return os.path.exists(self._directory)

    def collect(self, paths):
        for path in paths or ():
            relpath = os.path.relpath(path, self._artifact_root)
            dst = os.path.join(self._directory, relpath)
            safe_mkdir(os.path.dirname(dst))
            if os.path.isdir(path):
                shutil.copytree(path, dst)
            else:
                shutil.copy(path, dst)
            self._relpaths.add(relpath)

    def extract(self):
        for dir_name, _, filenames in safe_walk(self._directory):
            for filename in filenames:
                filename = os.path.join(dir_name, filename)
                relpath = os.path.relpath(filename, self._directory)
                dst = os.path.join(self._artifact_root, relpath)
                safe_mkdir_for(dst)
                shutil.copy(filename, dst)
                self._relpaths.add(relpath)


class TarballArtifact(Artifact):
    """An artifact stored in a tarball."""

    NATIVE_BINARY = None

    # TODO: Expose `dereference` for tasks.
    # https://github.com/pantsbuild/pants/issues/3961
    def __init__(
        self, artifact_root, artifact_extraction_root, tarfile_, compression=9, dereference=True
    ):
        super().__init__(artifact_root)
        self.artifact_extraction_root = artifact_extraction_root
        self._tarfile = tarfile_
        self._compression = compression
        self._dereference = dereference

    def exists(self):
        return os.path.isfile(self._tarfile)

    def collect(self, paths):
        # In our tests, gzip is slightly less compressive than bzip2 on .class files,
        # but decompression times are much faster.
        mode = "w:gz"

        tar_kwargs = {
            "dereference": self._dereference,
            "errorlevel": 2,
            "compresslevel": self._compression,
        }

        with open_tar(self._tarfile, mode, **tar_kwargs) as tarout:
            for path in paths or ():
                # Adds dirs recursively.
                relpath = os.path.relpath(path, self._artifact_root)
                tarout.add(path, relpath)
                self._relpaths.add(relpath)

    def extract(self):
        # Note(yic): unlike the python implementation before, now we do not update self._relpath
        # after the extraction.
        try:
            self.NATIVE_BINARY.decompress_tarball(
                self._tarfile.encode(), self.artifact_extraction_root.encode()
            )
        except Exception as e:
            raise ArtifactError("Extracting artifact failed:\n{}".format(e))
