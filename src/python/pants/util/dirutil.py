# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import atexit
import errno
import os
import shutil
import stat
import tempfile
import threading
import uuid
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import (
    Any,
    Callable,
    DefaultDict,
    FrozenSet,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
    overload,
)

from typing_extensions import Literal

from pants.util.strutil import ensure_text


def longest_dir_prefix(path: str, prefixes: Sequence[str]) -> Optional[str]:
    """Given a list of prefixes, return the one that is the longest prefix to the given path.

    Returns None if there are no matches.
    """
    longest_match, longest_prefix = 0, None
    for prefix in prefixes:
        if fast_relpath_optional(path, prefix) is not None and len(prefix) > longest_match:
            longest_match, longest_prefix = len(prefix), prefix

    return longest_prefix


def fast_relpath(path: str, start: str) -> str:
    """A prefix-based relpath, with no normalization or support for returning `..`."""
    relpath = fast_relpath_optional(path, start)
    if relpath is None:
        raise ValueError(f"{start} is not a directory containing {path}")
    return relpath


def fast_relpath_optional(path: str, start: str) -> Optional[str]:
    """A prefix-based relpath, with no normalization or support for returning `..`.

    Returns None if `start` is not a directory-aware prefix of `path`.
    """
    if len(start) == 0:
        # Empty prefix.
        return path

    # Determine where the matchable prefix ends.
    pref_end = len(start) - 1 if start[-1] == "/" else len(start)
    if pref_end > len(path):
        # The prefix is too long to match.
        return None
    elif path[:pref_end] == start[:pref_end] and (len(path) == pref_end or path[pref_end] == "/"):
        # The prefix matches, and the entries are either identical, or the suffix indicates that
        # the prefix is a directory.
        return path[pref_end + 1 :]
    return None


def ensure_relative_file_name(path: Path) -> str:
    """Return a string representing the `path`, with a leading './'.

    This ensures that the returned string can be used as the executable file when executing a
    subprocess, without putting the executable file on the PATH.
    """
    if path.is_absolute():
        raise ValueError(f"path {path} is expected to be relative!")
    return f"./{path}"


def safe_mkdir(directory: str, clean: bool = False) -> None:
    """Ensure a directory is present.

    If it's not there, create it.  If it is, no-op. If clean is True, ensure the dir is empty.

    :API: public
    """
    if clean:
        safe_rmtree(directory)
    try:
        os.makedirs(directory)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def safe_mkdir_for(path: str, clean: bool = False) -> None:
    """Ensure that the parent directory for a file is present.

    If it's not there, create it. If it is, no-op.
    """
    safe_mkdir(os.path.dirname(path), clean=clean)


def safe_mkdir_for_all(paths: Sequence[str]) -> None:
    """Make directories which would contain all of the passed paths.

    This avoids attempting to re-make the same directories, which may be noticeably expensive if
    many paths mostly fall in the same set of directories.
    """
    created_dirs: Set[str] = set()
    for path in paths:
        dir_to_make = os.path.dirname(path)
        if dir_to_make not in created_dirs:
            safe_mkdir(dir_to_make)
            created_dirs.add(dir_to_make)


def safe_file_dump(
    filename: str, payload: Union[bytes, str] = "", mode: str = "w", makedirs: bool = False
) -> None:
    """Write a string to a file.

    This method is "safe" to the extent that `safe_open` is "safe". See the explanation on the method
    doc there.

    When `payload` is an empty string (the default), this method can be used as a concise way to
    create an empty file along with its containing directory (or truncate it if it already exists).

    :param filename: The filename of the file to write to.
    :param payload: The string to write to the file.
    :param mode: A mode argument for the python `open` builtin which should be a write mode variant.
                 Defaults to 'w'.
    :param makedirs: Whether to make all parent directories of this file before making it.
    """
    if makedirs:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
    with safe_open(filename, mode=mode) as f:
        f.write(payload)


@overload
def maybe_read_file(filename: str) -> Optional[str]:
    ...


@overload
def maybe_read_file(filename: str, binary_mode: Literal[False]) -> Optional[str]:
    ...


@overload
def maybe_read_file(filename: str, binary_mode: Literal[True]) -> Optional[bytes]:
    ...


@overload
def maybe_read_file(filename: str, binary_mode: bool) -> Optional[Union[bytes, str]]:
    ...


def maybe_read_file(filename: str, binary_mode: bool = False) -> Optional[Union[bytes, str]]:
    """Read and return the contents of a file in a single file.read().

    :param filename: The filename of the file to read.
    :param binary_mode: Read from file as bytes or unicode.
    :returns: The contents of the file, or None if opening the file fails for any reason
    """
    try:
        return read_file(filename, binary_mode=binary_mode)
    except IOError:
        return None


@overload
def read_file(filename: str) -> str:
    ...


@overload
def read_file(filename: str, binary_mode: Literal[False]) -> str:
    ...


@overload
def read_file(filename: str, binary_mode: Literal[True]) -> bytes:
    ...


@overload
def read_file(filename: str, binary_mode: bool) -> Union[str, bytes]:
    ...


def read_file(filename: str, binary_mode: bool = False) -> Union[bytes, str]:
    """Read and return the contents of a file in a single file.read().

    :param filename: The filename of the file to read.
    :param binary_mode: Read from file as bytes or unicode.
    :returns: The contents of the file.
    """
    mode = "rb" if binary_mode else "r"
    with open(filename, mode) as f:
        content: Union[bytes, str] = f.read()
        return content


def safe_walk(path: Union[bytes, str], **kwargs: Any) -> Iterator[Tuple[str, List[str], List[str]]]:
    """Just like os.walk, but ensures that the returned values are unicode objects.

    This isn't strictly safe, in that it is possible that some paths
    will not be decodeable, but that case is rare, and the only
    alternative is to somehow avoid all interaction between paths and
    unicode objects, which seems especially tough in the presence of
    unicode_literals. See e.g.
    https://mail.python.org/pipermail/python-dev/2008-December/083856.html

    :API: public
    """
    # If os.walk is given a text argument, it yields text values; if it
    # is given a binary argument, it yields binary values.
    return os.walk(ensure_text(path), **kwargs)


class ExistingFileError(ValueError):
    """Indicates a copy operation would over-write a file with a directory."""


class ExistingDirError(ValueError):
    """Indicates a copy operation would over-write a directory with a file."""


def mergetree(src: str, dst: str, symlinks: bool = False, ignore=None, file_filter=None) -> None:
    """Just like `shutil.copytree`, except the `dst` dir may exist.

    The `src` directory will be walked and its contents copied into `dst`. If `dst` already exists
    the `src` tree will be overlayed in it; ie: existing files in `dst` will be over-written with
    files from `src` when they have the same subtree path.
    """
    safe_mkdir(dst)

    if not file_filter:
        file_filter = lambda _: True

    for src_path, dirnames, filenames in safe_walk(src, topdown=True, followlinks=True):
        ignorenames: FrozenSet[str] = frozenset()
        if ignore:
            to_ignore = ignore(src_path, dirnames + filenames)
            if to_ignore:
                ignorenames = frozenset(to_ignore)

        src_relpath = os.path.relpath(src_path, src)
        dst_path = os.path.join(dst, src_relpath)

        visit_dirs = []
        for dirname in dirnames:
            if dirname in ignorenames:
                continue

            src_dir = os.path.join(src_path, dirname)
            dst_dir = os.path.join(dst_path, dirname)
            if os.path.exists(dst_dir):
                if not os.path.isdir(dst_dir):
                    raise ExistingFileError(
                        "While copying the tree at {} to {}, encountered directory {} in "
                        "the source tree that already exists in the destination as a "
                        "non-directory.".format(src, dst, dst_dir)
                    )
                visit_dirs.append(dirname)
            elif symlinks and os.path.islink(src_dir):
                link = os.readlink(src_dir)
                os.symlink(link, dst_dir)
                # We need to halt the walk at a symlink dir; so we do not place dirname in visit_dirs
                # here.
            else:
                os.makedirs(dst_dir)
                visit_dirs.append(dirname)

        # In-place mutate dirnames to halt the walk when the dir is ignored by the caller.
        dirnames[:] = visit_dirs

        for filename in filenames:
            if filename in ignorenames:
                continue
            src_file_relpath = os.path.join(src_relpath, filename)
            if not file_filter(src_file_relpath):
                continue

            dst_filename = os.path.join(dst_path, filename)
            if os.path.exists(dst_filename):
                if not os.path.isfile(dst_filename):
                    raise ExistingDirError(
                        "While copying the tree at {} to {}, encountered file {} in the "
                        "source tree that already exists in the destination as a non-file.".format(
                            src, dst, dst_filename
                        )
                    )
                else:
                    os.unlink(dst_filename)
            src_filename = os.path.join(src_path, filename)
            if symlinks and os.path.islink(src_filename):
                link = os.readlink(src_filename)
                os.symlink(link, dst_filename)
            else:
                shutil.copy2(src_filename, dst_filename)


_MkdtempCleanerType = Callable[[], None]
_MKDTEMP_CLEANER: Optional[_MkdtempCleanerType] = None
_MKDTEMP_DIRS: DefaultDict[int, Set[str]] = defaultdict(set)
_MKDTEMP_LOCK = threading.RLock()


def _mkdtemp_atexit_cleaner() -> None:
    for td in _MKDTEMP_DIRS.pop(os.getpid(), []):
        safe_rmtree(td)


def _mkdtemp_unregister_cleaner() -> None:
    global _MKDTEMP_CLEANER
    _MKDTEMP_CLEANER = None


def _mkdtemp_register_cleaner(cleaner: _MkdtempCleanerType) -> None:
    global _MKDTEMP_CLEANER
    assert callable(cleaner)
    if _MKDTEMP_CLEANER is None:
        atexit.register(cleaner)
        _MKDTEMP_CLEANER = cleaner


def safe_mkdtemp(cleaner: _MkdtempCleanerType = _mkdtemp_atexit_cleaner, **kw: Any) -> str:
    """Create a temporary directory that is cleaned up on process exit.

    Arguments are as to tempfile.mkdtemp.

    :API: public
    """
    # Proper lock sanitation on fork [issue 6721] would be desirable here.
    with _MKDTEMP_LOCK:
        return register_rmtree(tempfile.mkdtemp(**kw), cleaner=cleaner)


def register_rmtree(directory: str, cleaner: _MkdtempCleanerType = _mkdtemp_atexit_cleaner) -> str:
    """Register an existing directory to be cleaned up at process exit."""
    with _MKDTEMP_LOCK:
        _mkdtemp_register_cleaner(cleaner)
        _MKDTEMP_DIRS[os.getpid()].add(directory)
    return directory


def safe_rmtree(directory: str) -> None:
    """Delete a directory if it's present. If it's not present, no-op.

    Note that if the directory argument is a symlink, only the symlink will
    be deleted.

    :API: public
    """
    if os.path.islink(directory):
        safe_delete(directory)
    else:
        shutil.rmtree(directory, ignore_errors=True)


def safe_open(filename, *args, **kwargs):
    """Open a file safely, ensuring that its directory exists.

    :API: public
    """
    safe_mkdir_for(filename)
    return open(filename, *args, **kwargs)


def safe_delete(filename: str) -> None:
    """Delete a file safely.

    If it's not present, no-op.
    """
    try:
        os.unlink(filename)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise


def safe_concurrent_rename(src: str, dst: str) -> None:
    """Rename src to dst, ignoring errors due to dst already existing.

    Useful when concurrent processes may attempt to create dst, and it doesn't matter who wins.
    """
    # Delete dst, in case it existed (with old content) even before any concurrent processes
    # attempted this write. This ensures that at least one process writes the new content.
    if os.path.isdir(src):  # Note that dst may not exist, so we test for the type of src.
        safe_rmtree(dst)
    else:
        safe_delete(dst)
    try:
        shutil.move(src, dst)
    except IOError as e:
        if e.errno != errno.EEXIST:
            raise


def safe_rm_oldest_items_in_dir(
    root_dir: str, num_of_items_to_keep: int, excludes: Iterable[str] = frozenset()
) -> None:
    """Keep `num_of_items_to_keep` newly modified items besides `excludes` in `root_dir` then remove
    the rest.

    :param root_dir: the folder to examine
    :param num_of_items_to_keep: number of files/folders/symlinks to keep after the cleanup
    :param excludes: absolute paths excluded from removal (must be prefixed with `root_dir`)
    """
    if os.path.isdir(root_dir):
        found_files = []
        for old_file in os.listdir(root_dir):
            full_path = os.path.join(root_dir, old_file)
            if full_path not in excludes:
                found_files.append((full_path, os.path.getmtime(full_path)))
        found_files = sorted(found_files, key=lambda x: x[1], reverse=True)
        for cur_file, _ in found_files[num_of_items_to_keep:]:
            rm_rf(cur_file)


@contextmanager
def safe_concurrent_creation(target_path: str) -> Iterator[str]:
    """A contextmanager that yields a temporary path and renames it to a final target path when the
    contextmanager exits.

    Useful when concurrent processes may attempt to create a file, and it doesn't matter who wins.

    :param target_path: The final target path to rename the temporary path to.
    :yields: A temporary path containing the original path with a unique (uuid4) suffix.
    """
    safe_mkdir_for(target_path)
    tmp_path = f"{target_path}.tmp.{uuid.uuid4().hex}"
    try:
        yield tmp_path
    except Exception:
        rm_rf(tmp_path)
        raise
    else:
        if os.path.exists(tmp_path):
            safe_concurrent_rename(tmp_path, target_path)


def chmod_plus_x(path: str) -> None:
    """Equivalent of unix `chmod a+x path`"""
    path_mode = os.stat(path).st_mode
    path_mode &= int("777", 8)
    if path_mode & stat.S_IRUSR:
        path_mode |= stat.S_IXUSR
    if path_mode & stat.S_IRGRP:
        path_mode |= stat.S_IXGRP
    if path_mode & stat.S_IROTH:
        path_mode |= stat.S_IXOTH
    os.chmod(path, path_mode)


def absolute_symlink(source_path: str, target_path: str) -> None:
    """Create a symlink at target pointing to source using the absolute path.

    :param source_path: Absolute path to source file
    :param target_path: Absolute path to intended symlink
    :raises ValueError if source_path or link_path are not unique, absolute paths
    :raises OSError on failure UNLESS file already exists or no such file/directory
    """
    if not os.path.isabs(source_path):
        raise ValueError(f"Path for source : {source_path} must be absolute")
    if not os.path.isabs(target_path):
        raise ValueError(f"Path for link : {target_path} must be absolute")
    if source_path == target_path:
        raise ValueError(f"Path for link is identical to source : {source_path}")
    try:
        if os.path.lexists(target_path):
            if os.path.islink(target_path) or os.path.isfile(target_path):
                os.unlink(target_path)
            else:
                shutil.rmtree(target_path)
        safe_mkdir_for(target_path)
        os.symlink(source_path, target_path)
    except OSError as e:
        # Another run may beat us to deletion or creation.
        if not (e.errno == errno.EEXIST or e.errno == errno.ENOENT):
            raise


def relative_symlink(source_path: str, link_path: str) -> None:
    """Create a symlink at link_path pointing to relative source.

    :param source_path: Absolute path to source file
    :param link_path: Absolute path to intended symlink
    :raises ValueError if source_path or link_path are not unique, absolute paths
    :raises OSError on failure UNLESS file already exists or no such file/directory
    """
    if not os.path.isabs(source_path):
        raise ValueError(f"Path for source:{source_path} must be absolute")
    if not os.path.isabs(link_path):
        raise ValueError(f"Path for link:{link_path} must be absolute")
    if source_path == link_path:
        raise ValueError(f"Path for link is identical to source:{source_path}")
    # The failure state below had a long life as an uncaught error. No behavior was changed here, it just adds a catch.
    # Raising an exception does differ from absolute_symlink, which takes the liberty of deleting existing directories.
    if os.path.isdir(link_path) and not os.path.islink(link_path):
        raise ValueError(f"Path for link would overwrite an existing directory: {link_path}")
    try:
        if os.path.lexists(link_path):
            os.unlink(link_path)
        rel_path = os.path.relpath(source_path, os.path.dirname(link_path))
        safe_mkdir_for(link_path)
        os.symlink(rel_path, link_path)
    except OSError as e:
        # Another run may beat us to deletion or creation.
        if not (e.errno == errno.EEXIST or e.errno == errno.ENOENT):
            raise


def symlink_is_correct(source_path, target_path):
    return (
        os.path.exists(source_path)
        and os.path.exists(target_path)
        and os.path.islink(target_path)
        and os.readlink(target_path) == source_path
    )


def relativize_path(path: str, rootdir: str) -> str:
    """
    :API: public
    """
    # Note that we can't test for length and return the shorter of the two, because we need these
    # paths to be stable across systems (e.g., because they get embedded in analysis files),
    # and this choice might be inconsistent across systems. So we assume the relpath is always
    # shorter. We relativize because of a known case of very long full path prefixes on Mesos,
    # so this seems like the right heuristic.
    # Note also that we mustn't call realpath on the path - we need to preserve the symlink structure.
    return os.path.relpath(path, rootdir)


# When running pants under mesos/aurora, the sandbox pathname can be very long. Since it gets
# prepended to most components in the classpath (some from ivy, the rest from the build),
# in some runs the classpath gets too big and exceeds ARG_MAX.
# We prevent this by using paths relative to the current working directory.
def relativize_paths(paths: Sequence[str], rootdir: str) -> List[str]:
    return [relativize_path(path, rootdir) for path in paths]


def touch(path: str, times: Optional[Union[int, Tuple[int, int]]] = None):
    """Equivalent of unix `touch path`.

    :API: public

    :path: The file to touch.
    :times Either a tuple of (atime, mtime) or else a single time to use for both.  If not
           specified both atime and mtime are updated to the current time.
    """
    if isinstance(times, tuple) and len(times) > 2:
        raise ValueError(
            "`times` must either be a tuple of (atime, mtime) or else a single time to use for both."
        )
    if isinstance(times, int):
        times = (times, times)
    with safe_open(path, "a"):
        os.utime(path, times)


def recursive_dirname(f: str) -> Iterator[str]:
    """Given a relative path like 'a/b/c/d', yield all ascending path components like:

    'a/b/c/d'
    'a/b/c'
    'a/b'
    'a'
    ''
    """
    prev = None
    while f != prev:
        yield f
        prev = f
        f = os.path.dirname(f)
    yield ""


def get_basedir(path: str) -> str:
    """Returns the base directory of a path.

    Examples:
      get_basedir('foo/bar/baz') --> 'foo'
      get_basedir('/foo/bar/baz') --> ''
      get_basedir('foo') --> 'foo'
    """
    return path[: path.index(os.sep)] if os.sep in path else path


def rm_rf(name: str) -> None:
    """Remove a file or a directory similarly to running `rm -rf <name>` in a UNIX shell.

    :param name: the name of the file or directory to remove.
    :raises: OSError on error.
    """
    if not os.path.exists(name):
        return

    try:
        # Avoid using safe_rmtree so we can detect failures.
        shutil.rmtree(name)
    except OSError as e:
        if e.errno == errno.ENOTDIR:
            # 'Not a directory', but a file. Attempt to os.unlink the file, raising OSError on failure.
            safe_delete(name)
        elif e.errno != errno.ENOENT:
            # Pass on 'No such file or directory', otherwise re-raise OSError to surface perm issues etc.
            raise


def split_basename_and_dirname(path: str) -> Tuple[str, str]:
    if not os.path.isfile(path):
        raise ValueError(f"{path} does not exist or is not a regular file.")
    return os.path.dirname(path), os.path.basename(path)


def check_no_overlapping_paths(paths: Iterable[str]) -> None:
    """Given a list of paths, ensure that all are unique and do not have the same prefix."""
    for path in paths:
        list_copy_without_path = list(paths)
        list_copy_without_path.remove(path)
        if path in list_copy_without_path:
            raise ValueError(f"{path} appeared more than once. All paths must be unique.")
        for p in list_copy_without_path:
            if path in p:
                raise ValueError(
                    f"{path} and {p} have the same prefix. All paths must be unique and cannot overlap."
                )


def is_executable(path: str) -> bool:
    """Returns whether a path names an existing executable file."""
    return os.path.isfile(path) and os.access(path, os.X_OK)


def is_readable_dir(path: str) -> bool:
    """Returns whether a path names an existing directory we can list and read files from."""
    return os.path.isdir(path) and os.access(path, os.R_OK) and os.access(path, os.X_OK)


def is_writable_dir(path: str) -> bool:
    """Returns whether a path names an existing directory that we can create and modify files in.

    We call is_readable_dir(), so this definition of "writable" is a superset of that.
    """
    return is_readable_dir(path) and os.access(path, os.W_OK)
