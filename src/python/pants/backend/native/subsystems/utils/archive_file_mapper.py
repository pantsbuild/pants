# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import os

from pants.subsystem.subsystem import Subsystem
from pants.util.collections import assert_single_element


class ArchiveFileMapper(Subsystem):
    """Index into known paths relative to a base directory.

    This is used with `NativeTool`s that wrap a compressed archive, which may have slightly
    different paths across platforms. The helper methods from this class make it concise to express
    searching for a single exact match for each of a set of directory path globs.
    """

    options_scope = "archive-file-mapper"

    class ArchiveFileMappingError(Exception):
        pass

    def assert_single_path_by_glob(self, components):
        """Assert that the path components (which are joined into a glob) match exactly one path.

        The matched path may be a file or a directory. This method is used to avoid having to guess
        platform-specific intermediate directory names, e.g. 'x86_64-linux-gnu' or 'x86_64-apple-
        darwin17.5.0'.
        """
        glob_path_string = os.path.join(*components)
        expanded_glob = glob.glob(glob_path_string)

        try:
            return assert_single_element(expanded_glob)
        except StopIteration as e:
            raise self.ArchiveFileMappingError(
                "No elements for glob '{}' -- expected exactly one.".format(glob_path_string), e
            )
        except ValueError as e:
            raise self.ArchiveFileMappingError(
                "Should have exactly one path matching expansion of glob '{}'.".format(
                    glob_path_string
                ),
                e,
            )

    def map_files(self, base_dir, all_components_list):
        """Apply `assert_single_path_by_glob()` to all elements of `all_components_list`.

        Each element of `all_components_list` should be a tuple of path components, including
        wildcards. The elements of each tuple are joined, and interpreted as a glob expression relative
        to `base_dir`. The resulting glob should match exactly one path.

        :return: List of matched paths, one per element of `all_components_list`.
        :raises: :class:`ArchiveFileMapper.ArchiveFileMappingError` if more or less than one path was
                 matched by one of the glob expressions interpreted from `all_components_list`.
        """
        mapped_paths = []
        for components_tupled in all_components_list:
            with_base = [base_dir] + list(components_tupled)
            # Results are known to exist, since they match a glob.
            mapped_paths.append(self.assert_single_path_by_glob(with_base))

        return mapped_paths
