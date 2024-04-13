# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib.resources as pkg_resources

from pants.backend.openapi import sample

PETSTORE_SAMPLE_SPEC = pkg_resources.read_text(sample.__name__, "petstore_spec.yaml")
