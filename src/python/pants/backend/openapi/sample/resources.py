# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib.resources

from pants.backend.openapi import sample

PETSTORE_SAMPLE_SPEC = importlib.resources.files(sample.__name__).joinpath("petstore_spec.yaml").read_text()
