# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from typing import Generator, Optional, Tuple

from pants.backend.docker.dockerfile import Dockerfile


@dataclass
class DockerfileDependencies:
    dockerfile: Dockerfile

    _pex_target_regexp = re.compile(
        r"""
        (?P<path>(?:\w\.?)+) / (?P<name>(?:\w\.?)+) \.pex$
        """,
        re.VERBOSE,
    )

    def putative_target_addresses(self) -> Tuple[str, ...]:
        """Inspect the Dockerfile for potential dependencies."""
        return tuple(self._putative_target_addresses())

    def _putative_target_addresses(self) -> Generator[str, None, None]:
        """Inspect the Dockerfile for potential dependencies."""
        for copy in self.dockerfile.copy:
            for src in copy.src:
                addr = self.as_address(src)
                if addr:
                    yield addr

    def as_address(self, value: str) -> Optional[str]:
        """Look for a string that looks like a path resulting from a packaged target, and return the
        likely target address that generated it.

        Such as foo.bar.baz/this.pex is likely from a pex_binary() target: //foo/bar/baz:this
        """
        pex = re.match(self._pex_target_regexp, value)
        if pex:
            path = pex.group("path").replace(".", "/")
            name = pex.group("name")
            return f"//{path}:{name}"

        return None
