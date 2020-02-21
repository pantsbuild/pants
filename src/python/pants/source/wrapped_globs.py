# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from abc import ABC, abstractmethod
from hashlib import sha1
from typing import Callable, Iterable, Iterator, List, Sequence, Tuple, cast

from twitter.common.dirutil.fileset import Fileset
from typing_extensions import TypedDict

from pants.base.build_environment import get_buildroot
from pants.base.parse_context import ParseContext
from pants.engine.fs import EMPTY_SNAPSHOT, Snapshot
from pants.util.dirutil import fast_relpath, fast_relpath_optional
from pants.util.memo import memoized_property


class _GlobsDict(TypedDict, total=True):
    globs: List[str]


class Filespec(_GlobsDict, total=False):
    """A dict of globs (required) and excludes (optional).

    For example: {'globs': ['list', 'of' , 'strings'], 'exclude': [{'globs' : ... }, ...] }

    The globs are in zglobs format.
    """

    exclude: List[_GlobsDict]


class FilesetWithSpec(ABC):
    """A set of files that keeps track of how we got it."""

    @staticmethod
    def empty(rel_root: str) -> "EagerFilesetWithSpec":
        """Creates an empty FilesetWithSpec object for the given rel_root."""
        return EagerFilesetWithSpec(rel_root, {"globs": []}, EMPTY_SNAPSHOT)

    @abstractmethod
    def matches(self, path_from_buildroot: str) -> bool:
        """Takes in any relative path from build root, and return whether it belongs to this
        filespec."""

    def __init__(self, rel_root: str, filespec: Filespec) -> None:
        """
    :param rel_root: The root for the given filespec, relative to the buildroot.
    :param filespec: A filespec as generated by `FilesetRelPathWrapper`, which represents
      what globs or file list it came from. Must be relative to the buildroot.
    """
        self.rel_root = rel_root
        self.filespec = filespec
        self._validate_globs_in_filespec(filespec, rel_root)

    @staticmethod
    def _validate_globs_in_filespec(filespec: Filespec, rel_root: str) -> None:
        def validate(globs_dict: _GlobsDict) -> None:
            for glob in globs_dict["globs"]:
                if not glob.startswith(rel_root):
                    raise ValueError(
                        f"expected glob filespec: {glob!r} to start with its root path: {rel_root!r}!"
                    )

        validate(filespec)
        exclude = filespec.get("exclude")
        if exclude:
            for exclude_filespec in exclude:
                validate(exclude_filespec)

    @property
    @abstractmethod
    def files(self) -> Sequence[str]:
        """Return the concrete set of files matched by this FilesetWithSpec, relative to
        `self.rel_root`."""

    @property
    @abstractmethod
    def files_hash(self) -> bytes:
        """Return a unique hash for this set of files."""

    def __iter__(self) -> Iterator[str]:
        return iter(self.files)

    def __getitem__(self, index: int) -> str:
        return self.files[index]

    def paths_from_buildroot_iter(self) -> Iterable[str]:
        """An alternative `__iter__` that joins files with the relative root."""
        for f in self:
            yield os.path.join(self.rel_root, f)


class EagerFilesetWithSpec(FilesetWithSpec):
    def __init__(
        self, rel_root: str, filespec: Filespec, snapshot: Snapshot, include_dirs: bool = False,
    ) -> None:
        """
    :param rel_root: The root for the given filespec, relative to the buildroot.
    :param filespec: A filespec as generated by `FilesetRelPathWrapper`, which represents
      what globs or file list it came from. Must be relative to buildroot.
    :param snapshot: A Snapshot of the files, rooted at the buildroot.
    """
        super().__init__(rel_root, filespec)
        self._include_dirs = include_dirs
        self._snapshot = snapshot

    @memoized_property
    def files(self) -> Tuple[str, ...]:  # type: ignore[override]  # superclass uses @property instead of @memoized_property
        return tuple(fast_relpath(path, self.rel_root) for path in self.files_relative_to_buildroot)

    @memoized_property
    def files_relative_to_buildroot(self) -> Tuple[str, ...]:
        res = self._snapshot.files
        if self._include_dirs:
            res += self._snapshot.dirs
        return res

    @property
    def files_hash(self) -> bytes:
        return self._snapshot.directory_digest.fingerprint.encode()

    @property
    def snapshot(self) -> Snapshot:
        return self._snapshot

    def __repr__(self) -> str:
        return "EagerFilesetWithSpec(rel_root={!r}, snapshot={!r})".format(
            self.rel_root, self._snapshot,
        )

    def matches(self, path_from_buildroot: str) -> bool:
        path_relative_to_rel_root = fast_relpath_optional(path_from_buildroot, self.rel_root)
        return path_relative_to_rel_root is not None and path_relative_to_rel_root in self.files


class LazyFilesetWithSpec(FilesetWithSpec):
    def __init__(
        self, rel_root: str, filespec: Filespec, files_calculator: Callable[[], Sequence[str]],
    ) -> None:
        """
    :param rel_root: The root for the given filespec, relative to the buildroot.
    :param filespec: A filespec as generated by `FilesetRelPathWrapper`, which represents
      what globs or file list it came from.
    :param files_calculator: A no-arg function that will lazily compute the file paths for
      this filespec.
    """
        super().__init__(rel_root, filespec)
        self._files_calculator = files_calculator

    @memoized_property
    def files(self) -> Sequence[str]:  # type: ignore[override]  # superclass uses @property instead of @memoized_property
        return self._files_calculator()

    @property
    def files_hash(self) -> bytes:
        h = sha1()
        for path in sorted(self.files):
            h.update(path.encode())
            with open(os.path.join(get_buildroot(), self.rel_root, path), "rb") as f:
                h.update(f.read())
        return h.digest()

    def matches(self, path_from_buildroot: str) -> bool:
        return any(
            path_from_buildroot == path_in_spec for path_in_spec in self.paths_from_buildroot_iter()
        )


class FilesetRelPathWrapper(ABC):
    KNOWN_PARAMETERS = frozenset({"exclude", "follow_links"})

    @property
    @abstractmethod
    def wrapped_fn(cls):
        """The wrapped file calculation function."""

    @property
    @abstractmethod
    def validate_files(cls) -> bool:
        """True to validate the existence of files returned by wrapped_fn."""

    def __init__(self, parse_context: ParseContext) -> None:
        self._parse_context = parse_context

    def __call__(self, *patterns, **kwargs) -> LazyFilesetWithSpec:
        return self.create_fileset_with_spec(self._parse_context.rel_path, *patterns, **kwargs)

    @classmethod
    def create_fileset_with_spec(
        cls, rel_path: str, *patterns: str, **kwargs
    ) -> LazyFilesetWithSpec:
        """
    :param rel_path: The relative path to create a FilesetWithSpec for.
    :param patterns: glob patterns to apply.
    :param exclude: A list of {,r,z}globs objects, strings, or lists of strings to exclude.
                    NB: this argument is contained within **kwargs!
    """
        for pattern in patterns:
            if not isinstance(pattern, str):
                raise ValueError(
                    "Expected string patterns for {}: got {}".format(cls.__name__, patterns)
                )

        raw_exclude = kwargs.pop("exclude", [])
        buildroot = get_buildroot()
        root = os.path.normpath(os.path.join(buildroot, rel_path))

        # making sure there are no unknown arguments.
        unknown_args = set(kwargs.keys()) - cls.KNOWN_PARAMETERS

        if unknown_args:
            raise ValueError(
                "Unexpected arguments while parsing globs: {}".format(", ".join(unknown_args))
            )

        for glob in patterns:
            if cls._is_glob_dir_outside_root(glob, root):
                raise ValueError(
                    "Invalid glob {}, points outside BUILD file root {}".format(glob, root)
                )

        exclude = cls.process_raw_exclude(raw_exclude)

        files_calculator = cls._file_calculator(root, patterns, kwargs, exclude)

        rel_root = fast_relpath(root, buildroot)
        if rel_root == ".":
            rel_root = ""
        filespec = cls.to_filespec(patterns, root=rel_root, exclude=exclude)

        return LazyFilesetWithSpec(rel_root, filespec, files_calculator)

    @classmethod
    def _file_calculator(cls, root, patterns, kwargs, exclude):
        def files_calculator():
            result = cls.wrapped_fn(root=root, *patterns, **kwargs)
            for ex in exclude:
                result -= ex

            # BUILD file's filesets should contain only files, not folders.
            return [
                path
                for path in result
                if not cls.validate_files or os.path.isfile(os.path.join(root, path))
            ]

        return files_calculator

    @staticmethod
    def _is_glob_dir_outside_root(glob: str, root: str) -> bool:
        # The assumption is that a correct glob starts with the root,
        # even after normalizing.
        glob_path = os.path.normpath(os.path.join(root, glob))

        # Check if the glob path has the correct root.
        return cast(bool, os.path.commonprefix([root, glob_path]) != root)

    @staticmethod
    def process_raw_exclude(raw_exclude):
        if isinstance(raw_exclude, str):
            raise ValueError(
                "Expected exclude parameter to be a list of globs, lists, or strings,"
                " but was a string: {}".format(raw_exclude)
            )

        # You can't subtract raw strings from globs
        def ensure_string_wrapped_in_list(element):
            if isinstance(element, str):
                return [element]
            return element

        return [ensure_string_wrapped_in_list(exclude) for exclude in raw_exclude]

    @classmethod
    def to_filespec(cls, args: Iterable[str], root: str = "", exclude=None,) -> Filespec:
        """Return a dict representation of this glob list, relative to the buildroot."""
        result: Filespec = {"globs": [os.path.join(root, arg) for arg in args]}
        if exclude:
            result["exclude"] = []
            for exclude in exclude:
                if hasattr(exclude, "filespec"):
                    result["exclude"].append(exclude.filespec)
                else:
                    result["exclude"].append({"globs": [os.path.join(root, x) for x in exclude]})
        return result


class Globs(FilesetRelPathWrapper):
    """Matches files in the BUILD file's directory.

    E.g., - ``sources = globs('*java'),`` to get .java files in this directory.
          - ``globs('*',exclude=[globs('*.java'), 'foo.py'])`` to get all files in this directory
            except ``.java`` files and ``foo.py``.
    """

    wrapped_fn = Fileset.globs
    validate_files = True


class RGlobs(FilesetRelPathWrapper):
    """Matches files recursively under the BUILD file's directory.

    E.g., ``bundle(fileset=rglobs('config/*'))`` to bundle up all files in the config, config/foo,
    config/foo/bar directories.
    """

    @staticmethod
    def rglobs_following_symlinked_dirs_by_default(*globspecs, **kw):
        if "follow_links" not in kw:
            kw["follow_links"] = True
        return Fileset.rglobs(*globspecs, **kw)

    wrapped_fn = rglobs_following_symlinked_dirs_by_default
    validate_files = True

    @classmethod
    def to_filespec(cls, args, root="", exclude=None):
        # In rglobs, * at the beginning of a path component means "any
        # number of directories, including 0". So every time we see ^*,
        # we need to output "**/*whatever".
        rglobs = []
        for arg in args:
            components = arg.split(os.path.sep)
            out = []
            for component in components:
                if component == "**":
                    if out and out[-1].startswith("**"):
                        continue
                    out.append(component)
                elif component[0] == "*":
                    if out and out[-1].startswith("**"):
                        # We want to translate *.py to **/*.py, not **/**/*.py
                        out.append(component)
                    else:
                        out.append("**/" + component)
                else:
                    out.append(component)

            rglobs.append(os.path.join(*out))

        return super().to_filespec(rglobs, root=root, exclude=exclude)


class ZGlobs(FilesetRelPathWrapper):
    """Matches files in the BUILD file's dir using zsh-style globs, including ``**/`` to recurse."""

    @staticmethod
    def zglobs_following_symlinked_dirs_by_default(*globspecs, **kw):
        if "follow_links" not in kw:
            kw["follow_links"] = True
        return Fileset.zglobs(*globspecs, **kw)

    wrapped_fn = zglobs_following_symlinked_dirs_by_default
    validate_files = True
