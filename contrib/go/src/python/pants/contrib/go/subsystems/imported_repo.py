# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import namedtuple


class ImportedRepo(namedtuple("_ImportedRepo", ["import_prefix", "vcs", "url"])):
    """The three values used to import a remote Go repo.

        - import_prefix: The alias of the root of the referenced repo, when used in import statements.
        - vcs: The type of VCS used by the referenced repo.
        - url: The repo's URL.

    These are the three values provided by the go-import meta tag, but they can also be derived from
    other sources (such as an explicit `import "example.org/repo.git/foo/bar"`).

    See https://golang.org/cmd/go/#hdr-Remote_import_paths .
    """
