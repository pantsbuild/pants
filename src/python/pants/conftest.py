# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

# The top-level `pants` module must be a namespace package, because we build two dists from it
# (pantsbuild.pants, and pantsbuild.pants.testutil) and consumers of these dists need to be
# able to import from both.
#
# In fact it is an *implicit* namespace package - that is, it has no __init__.py file.
# See https://packaging.python.org/guides/packaging-namespace-packages/ .
#
# Unfortunately, the presence or absence of __init__.py affects how pytest determines the
# module names for test code. For details see
# https://docs.pytest.org/en/stable/goodpractices.html#test-package-name .
#
# Usually this doesn't matter, as tests don't typically care about their own module name.
# But we have tests (notably those in src/python/pants/engine) that create @rules and
# expect them to have certain names. And @rule names are generated from the name of the module
# containing the rule function...
#
# To allow those tests to work naturally (with expected module names relative to `src/python`)
# we artificially create `src/python/pants/__init__.py` in the test sandbox, to force
# pytest to determine module names relative to `src/python` (instead of `src/python/pants`).
#
# Note that while this makes the (implicit) namespace package into a regular package,
# that is fine at test time. We don't consume testutil from a dist but from source, in the same
# source root (src/python). We only need `pants` to be a namespace package in the dists we create.

Path("src/python/pants/__init__.py").touch()
