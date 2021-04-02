# Copyright 2021 Pants project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.shell.lint.shellcheck.rules import rules as shellcheck_rules


def rules():
    return shellcheck_rules()
