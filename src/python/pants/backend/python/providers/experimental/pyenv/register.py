# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.providers.pyenv.rules import rules as pyenv_rules


def rules():
    return pyenv_rules()
