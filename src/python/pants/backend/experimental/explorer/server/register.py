# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.explorer.server.rules import rules as server_rules


def rules():
    return server_rules()
