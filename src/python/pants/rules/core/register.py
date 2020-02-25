# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.rules.core import (
    binary,
    cloc,
    determine_specified_source_files,
    distdir,
    filedeps,
    fmt,
    lint,
    list_roots,
    list_targets,
    repl,
    run,
    strip_source_roots,
    test,
)


def rules():
    return [
        *cloc.rules(),
        *binary.rules(),
        *fmt.rules(),
        *lint.rules(),
        *list_roots.rules(),
        *list_targets.rules(),
        *determine_specified_source_files.rules(),
        *filedeps.rules(),
        *repl.rules(),
        *run.rules(),
        *strip_source_roots.rules(),
        *distdir.rules(),
        *test.rules(),
    ]
