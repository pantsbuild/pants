# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.dependency_inference.python_stdlib import py27, py35, py36, py37, py38

combined_stdlib = py27.stdlib | py35.stdlib | py36.stdlib | py37.stdlib | py38.stdlib
