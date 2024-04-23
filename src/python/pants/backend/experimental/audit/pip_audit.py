# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

import requests
from packaging.requirements import Requirement

logger = logging.getLogger(__name__)


@dataclass
class VulnerabilityData:
    """Represents a vulnerability in some python package."""

    vuln_id: str  # A service-provided identifier for the vulnerability.
    details: str  # A human-readable description of the vulnerability. Can be extremely long.
    fixed_in: List[
        str
    ]  # A list of versions that can be upgraded to that resolve the vulnerability.
    aliases: Set[str]  # A set of aliases (alternative identifiers) for this result.
    link: str  # A link to the vulnerability info.
    summary: str  # An optional short form human readable description.
    withdrawn: bool  # Represents whether the vulnerability has been withdrawn.

    @classmethod
    def from_raw_data(self, data):
        return VulnerabilityData(
            vuln_id=data["id"],
            details=data["details"],
            fixed_in=data["fixed_in"],
            aliases=data["aliases"],
            link=data["link"],
            summary=data["summary"],
            withdrawn=data["withdrawn"],
        )


def audit_constraints_strings(constraints_strings, session, excludes_ids) -> Dict[str, str]:
    """Retrieve security warnings for the given constraints from the Pypi json API."""
    vulnerabilities = {}
    for constraint_string in constraints_strings:
        requirement = Requirement(constraint_string)
        specifiers = list(requirement.specifier)
        if len(specifiers) != 1:
            raise ValueError(
                "Unexpected specifier from a lockfile (not exactly one): {}", specifiers
            )
        specifier = specifiers[0]
        results = audit_constraints_string(
            package_name=requirement.name,
            version=specifier.version,
            session=session,
        )
        if results is None:
            continue
        vulnerabilities[str(requirement)] = [
            result for result in results if result.vuln_id not in excludes_ids
        ]
    return vulnerabilities


def audit_constraints_string(
    package_name: str, version: str, session: requests.Session
) -> Optional[str]:
    url = f"https://pypi.org/pypi/{package_name}/{str(version)}/json"
    response = session.get(url=url)
    response.raise_for_status()
    response_json = response.json()
    vulnerabilities = response_json.get("vulnerabilities")
    if vulnerabilities:
        vulns = [VulnerabilityData.from_raw_data(vuln_data) for vuln_data in vulnerabilities]
        print(vulns)
        return vulns
