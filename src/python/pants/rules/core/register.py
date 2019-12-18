# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.rules.core import (
  binary,
  cloc,
  distdir,
  filedeps,
  fmt,
  generate_pants_ini,
  lint,
  list_roots,
  list_targets,
  run,
  strip_source_root,
  test,
)


def rules():
  return [
    *cloc.rules(),
    *binary.rules(),
    *fmt.rules(),
    *generate_pants_ini.rules(),
    *lint.rules(),
    *list_roots.rules(),
    *list_targets.rules(),
    *filedeps.rules(),
    *run.rules(),
    *strip_source_root.rules(),
    *distdir.rules(),
    *test.rules()
  ]
