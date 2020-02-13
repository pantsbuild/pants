# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.rules.core import (
  binary,
  cloc,
  distdir,
  filedeps,
  find_target_source_files,
  fmt,
  lint,
  list_roots,
  list_targets,
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
    *find_target_source_files.rules(),
    *filedeps.rules(),
    *run.rules(),
    *strip_source_roots.rules(),
    *distdir.rules(),
    *test.rules()
  ]
