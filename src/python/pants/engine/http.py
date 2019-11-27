# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass


@dataclass(frozen=True)
class HttpResponse:
  pass


@dataclass(frozen=True)
class MakeHttpRequest:
  pass


def create_http_rules():
  return []
