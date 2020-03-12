# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.rules.build_file_manipulation.buildozer_commands import rules as buildozer_commands_rules
from pants.rules.build_file_manipulation.match_cst_nodes import rules as match_cst_nodes_rules


def rules():
    return [
        *buildozer_commands_rules(),
        *match_cst_nodes_rules(),
    ]
