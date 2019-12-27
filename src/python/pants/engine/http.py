# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.engine.rules import RootRule


@dataclass(frozen=True)
class HttpResponse:
  url: str
  response_code: Optional[int]
  output_bytes: Optional[bytes]
  headers: Tuple[Tuple[str, str], ...]


@dataclass(frozen=True)
class MakeHttpRequest:
  url: str
  headers: Tuple[str, ...] = ()
  invalidation_token: str = ''


def create_http_rules():
  return [
    RootRule(MakeHttpRequest),
  ]
