# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resource(name="lockfile", source="yamllint.lock")

python_sources(dependencies=[":lockfile"])

python_tests(name="tests")
