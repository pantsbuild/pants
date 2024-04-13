# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.framework.django import dependency_inference, detect_apps


def rules():
    return [
        *detect_apps.rules(),
        *dependency_inference.rules(),
    ]
