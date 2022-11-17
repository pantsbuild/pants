# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: Mark this as an explicit namespace packages, so that `pants.testutil`
# can be loaded, if installed.
__path__ = __import__('pkgutil').extend_path(__path__, __name__)
