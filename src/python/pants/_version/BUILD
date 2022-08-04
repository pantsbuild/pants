# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This package is used to provide a non-namespaced Python package from which
# `importlib.resources.read_binary` can read our `VERSION` file. The `VERSION` file is a
# symlink to the concrete `VERSION` file in `src/python/pants`. This creates a minimal package
# that can be imported by `pants.version` during tests, and inferred by Pants as a dependency.
# Future versions of  `importlib.resources` will be able to read resources from namespace
# packages, at which point, this package will no longer need to exist.

python_sources(dependencies=["./VERSION:resources"])
resources(name="resources", sources=["VERSION"])
