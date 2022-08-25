# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resource(
    name="dependency_parser",
    source="dependency_parser_py",
)

# Also expose scripts as python sources so they get formatted/linted/checked.
python_source(
    name="dependency_parser_source",
    source="dependency_parser_py",
    # This is run with Python 2.7 and 3.5+, so we shouldn't be running pyupgrade.
    # skip_pyupgrade=True,
)
