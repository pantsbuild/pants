# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class OtlpParameters:
    endpoint: str | None
    traces_endpoint: str | None
    certificate_file: str | None
    client_key_file: str | None
    client_certificate_file: str | None
    headers: Mapping[str, str] | None
    timeout: int | None
    compression: str | None

    def resolve_traces_endpoint(self) -> str:
        if self.traces_endpoint:
            return self.traces_endpoint

        if not self.endpoint:
            return "http://localhost:4317"

        url = urllib.parse.urlparse(self.endpoint)
        scheme = url.scheme if url.scheme else "http"
        path = url.path
        if not path.endswith("/"):
            path = path + "/"
        path = f"{path}/v1/traces"
        url = url._replace(scheme=scheme, path=path)
        return url.geturl()
