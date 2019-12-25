# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.rules.shell_scripts.bash import rules as bash_rules


def rules():
  return [
    *bash_rules(),
  ]
