# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: Mark this as an explicit namespace package, so that `pants.testutil`
# can be loaded, if installed.
# (We can't rely on an implicit namespace package as pytest chooses package names based on the absence
# or presence of this file: https://docs.pytest.org/en/stable/explanation/goodpractices.html#test-package-name)
__path__ = __import__("pkgutil").extend_path(__path__, __name__)
