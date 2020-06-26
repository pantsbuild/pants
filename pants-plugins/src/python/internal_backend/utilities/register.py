# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from typing import Dict, List, Optional, cast

from packaging.version import Version

from pants.backend.python.python_artifact import PythonArtifact
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.rules import SubsystemRule
from pants.subsystem.subsystem import Subsystem
from pants.util.ordered_set import FrozenOrderedSet
from pants.version import PANTS_SEMVER, VERSION


def pants_setup_py(
    name: str, description: str, additional_classifiers: Optional[List[str]] = None, **kwargs
) -> PythonArtifact:
    """Creates the setup_py for a Pants artifact.

    :param name: The name of the package.
    :param description: A brief description of what the package provides.
    :param additional_classifiers: Any additional trove classifiers that apply to the package,
                                        see: https://pypi.org/pypi?%3Aaction=list_classifiers
    :param kwargs: Any additional keyword arguments to be passed to `setuptools.setup
                   <https://pythonhosted.org/setuptools/setuptools.html>`_.
    :returns: A setup_py suitable for building and publishing Pants components.
    """
    if not name.startswith("pantsbuild.pants"):
        raise ValueError(
            f"Pants distribution package names must start with 'pantsbuild.pants', given {name}"
        )

    standard_classifiers = [
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        # We know for a fact these OSs work but, for example, know Windows
        # does not work yet.  Take the conservative approach and only list OSs
        # we know pants works with for now.
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python",
        "Topic :: Software Development :: Build Tools",
    ]
    classifiers = FrozenOrderedSet(standard_classifiers + (additional_classifiers or []))

    notes = PantsReleases.global_instance().notes_for_version(PANTS_SEMVER)

    return PythonArtifact(
        name=name,
        version=VERSION,
        description=description,
        long_description=Path("src/python/pants/ABOUT.rst").read_text() + notes,
        long_description_content_type="text/x-rst",
        url="https://github.com/pantsbuild/pants",
        project_urls={
            "Documentation": "https://www.pantsbuild.org/",
            "Source": "https://github.com/pantsbuild/pants",
            "Tracker": "https://github.com/pantsbuild/pants/issues",
        },
        license="Apache License, Version 2.0",
        zip_safe=True,
        classifiers=list(classifiers),
        **kwargs,
    )


class PantsReleases(Subsystem):
    """A subsystem to hold per-pants-release configuration."""

    options_scope = "pants-releases"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--branch-notes",
            type=dict,
            help="A dict from branch name to release notes rst-file location.",
        )

    @property
    def _branch_notes(self) -> Dict[str, str]:
        return cast(Dict[str, str], self.options.branch_notes)

    @classmethod
    def _branch_name(cls, version: Version) -> str:
        """Defines a mapping between versions and branches.

        All releases, including dev releases, map to a particular branch page.
        """
        suffix = version.public[len(version.base_version) :]
        components = version.base_version.split(".") + [suffix]
        if suffix != "" and not (suffix.startswith("rc") or suffix.startswith(".dev")):
            raise ValueError(f"Unparseable pants version number: {version}")
        return "{}.{}.x".format(*components[:2])

    def notes_for_version(self, version: Version) -> str:
        """Given the parsed Version of pants, return its release notes."""
        branch_name = self._branch_name(version)
        branch_notes_file = self._branch_notes.get(branch_name, None)
        if branch_notes_file is None:
            raise ValueError(
                f"Version {version} lives in branch {branch_name}, which is not configured in "
                f"{self._branch_notes}."
            )
        return Path(branch_notes_file).read_text()


def build_file_aliases():
    return BuildFileAliases(objects={"pants_setup_py": pants_setup_py})

def rules():
    return [SubsystemRule(PantsReleases)]
