import logging

import requests
from packaging.requirements import Requirement

from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


def audit_constraints_strings(constraints_strings, session):
    """Retrieve security warnings for the given constraints from the Pypi json API."""
    vulnerabilities = {}
    for constraint_string in constraints_strings:
        requirement = Requirement(constraint_string)
        result = audit_constraints_string(
            package_name=requirement.name,
            version=str(requirement.specifier)[2:],
            session=session,
        )
        if result is not None:
            vulnerabilities[str(requirement)] = result
    return vulnerabilities


def audit_constraints_string(package_name: str, version: str, session: requests.Session):

    url = f"https://pypi.org/pypi/{package_name}/{str(version)}/json"
    response = session.get(url=url)
    response.raise_for_status()
    response_json = response.json()
    return response_json.get("vulnerabilities") or None
