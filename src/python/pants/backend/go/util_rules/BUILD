# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":go_sources"])
python_tests(name="tests", timeout=120)

resources(name="go_sources", sources=["*.go"])
