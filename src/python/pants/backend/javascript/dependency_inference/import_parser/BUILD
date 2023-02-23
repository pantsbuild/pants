# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
python_sources(dependencies=[":javascript_source_import_parser_resources"])

python_tests(name="tests0")

resources(
    name="javascript_source_import_parser_resources",
    sources=["*.cjs", "package-lock.json", "package.json"],
)

javascript_sources(
    name="import_parser0",
)

package_json(
    name="import_parser1",
)
