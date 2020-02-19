# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from django.utils import text

assert "forty-two" == text.slugify("forty two")
