# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.providers.pbs.rules import rules as pbs_rules


def rules():
    return pbs_rules()
