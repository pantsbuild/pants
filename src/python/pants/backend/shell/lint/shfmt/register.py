# Copyright 2021 Pants project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.shell.lint import shell_fmt
from pants.backend.shell.lint.shfmt.rules import rules as shfmt_rules


def rules():
    return [*shfmt_rules(), *shell_fmt.rules()]
