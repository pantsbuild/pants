# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import requests

from pants.engine.rules import side_effecting


@dataclass(frozen=True)
class HttpGetResponse:
  url: str
  status_code: Optional[int]
  output_bytes: Optional[bytes]
  headers: Tuple[Tuple[str, str], ...]


@side_effecting
@dataclass(frozen=True)
class HttpRequester:

  def get_request(self, url: str, *, headers: Optional[Dict[str, str]] = None) -> HttpGetResponse:
    r = requests.get(url, headers=headers)
    header_list = tuple((str(item), r.headers[item]) for item in r.headers)
    return HttpGetResponse(
      url=r.url,
      headers=header_list,
      status_code=r.status_code,
      output_bytes=r.content,
    )
