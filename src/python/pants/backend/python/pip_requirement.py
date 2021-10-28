# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

import pkg_resources

logger = logging.getLogger(__name__)


class PipRequirement:
    """A Pip-style requirement.

    Currently just a drop-in replacement for pkg_resources.Requirement.

    TODO:  Once this class has fully replaced relevant uses of pkg_resources.Requirement,
      we will enhance this class to support Pip requirements that are not parseable by
      pkg_resources.Requirement, such as old-style VCS requirements, --hash option suffixes etc.
    """

    @classmethod
    def parse(cls, line: str) -> PipRequirement:
        return cls(pkg_resources.Requirement.parse(line))

    def __init__(self, req: pkg_resources.Requirement):
        self._req = req

    def as_pkg_resources_requirement(self) -> pkg_resources.Requirement:
        return self._req

    @property
    def project_name(self) -> str:
        return self._req.project_name

    @property
    def specs(self):
        return self._req.specs

    @property
    def url(self):
        return self._req.url

    def __hash__(self):
        return hash(self._req)

    def __eq__(self, other):
        # Semantic equality requires parsing the specifier (since order in it doesn't matter).
        if not isinstance(other, self.__class__):
            return False
        return self._req == other._req

    def __str__(self):
        return str(self._req)
