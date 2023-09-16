# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import hashlib
import json
import os
from collections import defaultdict
from enum import Enum
from hashlib import sha1

from pants.base.build_environment import get_buildroot
from pants.option.custom_types import UnsetBool, dict_with_files_option, dir_option, file_option
from pants.util.strutil import softwrap


class OptionEncoder(json.JSONEncoder):
    def default(self, o):
        if o is UnsetBool:
            return "_UNSET_BOOL_ENCODING"
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, dict):
            # Sort by key to ensure that we don't invalidate if the insertion order changes.
            return {k: self.default(v) for k, v in sorted(o.items())}
        return super().default(o)


def stable_option_fingerprint(obj):
    json_str = json.dumps(
        obj, ensure_ascii=True, allow_nan=False, sort_keys=True, cls=OptionEncoder
    )
    digest = hashlib.sha1()
    digest.update(json_str.encode("utf8"))
    return digest.hexdigest()


class OptionsFingerprinter:
    """Handles fingerprinting options under a given build_graph.

    :API: public
    """

    @classmethod
    def combined_options_fingerprint_for_scope(cls, scope, options, daemon_only=False) -> str:
        """Given options and a scope, compute a combined fingerprint for the scope.

        :param string scope: The scope to fingerprint.
        :param Options options: The `Options` object to fingerprint.
        :param daemon_only: Whether to fingerprint only daemon=True options.
        :return: Hexadecimal string representing the fingerprint for all `options`
                 values in `scope`.
        """
        fingerprinter = cls()
        hasher = sha1()
        pairs = options.get_fingerprintable_for_scope(scope, daemon_only)
        for option_type, option_value in pairs:
            fingerprint = fingerprinter.fingerprint(option_type, option_value)
            if fingerprint is None:
                # This isn't necessarily a good value to be using here, but it preserves behavior from
                # before the commit which added it. I suspect that using the empty string would be
                # reasonable too, but haven't done any archaeology to check.
                fingerprint = "None"
            hasher.update(fingerprint.encode())
        return hasher.hexdigest()

    def fingerprint(self, option_type, option_val):
        """Returns a hash of the given option_val based on the option_type.

        :API: public

        Returns None if option_val is None.
        """
        if option_val is None:
            return None

        # Wrapping all other values in a list here allows us to easily handle single-valued and
        # list-valued options uniformly. For non-list-valued options, this will be a singleton list
        # (with the exception of dict, which is not modified). This dict exception works because we do
        # not currently have any "list of dict" type, so there is no ambiguity.
        if not isinstance(option_val, (list, tuple, dict)):
            option_val = [option_val]

        if option_type == dir_option:
            return self._fingerprint_dirs(option_val)
        elif option_type == file_option:
            return self._fingerprint_files(option_val)
        elif option_type == dict_with_files_option:
            return self._fingerprint_dict_with_files(option_val)
        else:
            return self._fingerprint_primitives(option_val)

    def _assert_in_buildroot(self, filepath):
        """Raises an error if the given filepath isn't in the buildroot.

        Returns the normalized, absolute form of the path.
        """
        filepath = os.path.normpath(filepath)
        root = get_buildroot()
        if not os.path.abspath(filepath) == filepath:
            # If not absolute, assume relative to the build root.
            return os.path.join(root, filepath)
        else:
            if ".." in os.path.relpath(filepath, root).split(os.path.sep):
                # The path wasn't in the buildroot. This is an error because it violates pants being
                # hermetic.
                raise ValueError(
                    softwrap(
                        f"""
                        Received a file_option that was not inside the build root:

                            file_option: {filepath}
                            build_root:  {root}
                        """
                    )
                )
            return filepath

    def _fingerprint_dirs(self, dirpaths, topdown=True, onerror=None, followlinks=False):
        """Returns a fingerprint of the given file directories and all their sub contents.

        This assumes that the file directories are of reasonable size to cause memory or performance
        issues.
        """
        # Note that we don't sort the dirpaths, as their order may have meaning.
        filepaths = []
        for dirpath in dirpaths:
            dirs = os.walk(dirpath, topdown=topdown, onerror=onerror, followlinks=followlinks)
            sorted_dirs = sorted(dirs, key=lambda d: d[0])
            filepaths.extend(
                [
                    os.path.join(dirpath, filename)
                    for dirpath, dirnames, filenames in sorted_dirs
                    for filename in sorted(filenames)
                ]
            )
        return self._fingerprint_files(filepaths)

    def _fingerprint_files(self, filepaths):
        """Returns a fingerprint of the given filepaths and their contents.

        This assumes the files are small enough to be read into memory.
        """
        hasher = sha1()
        # Note that we don't sort the filepaths, as their order may have meaning.
        for filepath in filepaths:
            filepath = self._assert_in_buildroot(filepath)
            hasher.update(os.path.relpath(filepath, get_buildroot()).encode())
            with open(filepath, "rb") as f:
                hasher.update(f.read())
        return hasher.hexdigest()

    def _fingerprint_primitives(self, val):
        return stable_option_fingerprint(val)

    @staticmethod
    def _fingerprint_dict_with_files(option_val):
        """Returns a fingerprint of the given dictionary containing file paths.

        Any value which is a file path which exists on disk will be fingerprinted by that file's
        contents rather than by its path.

        This assumes the files are small enough to be read into memory.

        NB: The keys of the dict are assumed to be strings -- if they are not, the dict should be
        converted to encode its keys with `stable_option_fingerprint()`, as is done in the `fingerprint()`
        method.
        """
        final = defaultdict(list)
        for k, v in option_val.items():
            for sub_value in sorted(v.split(",")):
                if os.path.isfile(sub_value):
                    with open(sub_value) as f:
                        final[k].append(f.read())
                else:
                    final[k].append(sub_value)
        fingerprint = stable_option_fingerprint(final)
        return fingerprint
