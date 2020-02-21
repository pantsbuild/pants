# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from django.urls import URLPattern

DEBUG: bool = True
DEFAULT_FROM_EMAIL: str = "webmaster@example.com"
SECRET_KEY: str = "not so secret"

MY_SETTING: URLPattern = URLPattern(pattern="foo", callback=lambda: None)
