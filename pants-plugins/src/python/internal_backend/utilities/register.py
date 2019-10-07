# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from pathlib import Path

from twitter.common.collections import OrderedSet

from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.subsystem.subsystem import Subsystem
from pants.version import PANTS_SEMVER, VERSION


def pants_setup_py(name, description, additional_classifiers=None, **kwargs):
    """Creates the setup_py for a pants artifact.

  :param str name: The name of the package.
  :param str description: A brief description of what the package provides.
  :param list additional_classifiers: Any additional trove classifiers that apply to the package,
                                      see: https://pypi.org/pypi?%3Aaction=list_classifiers
  :param kwargs: Any additional keyword arguments to be passed to `setuptools.setup
                 <https://pythonhosted.org/setuptools/setuptools.html>`_.
  :returns: A setup_py suitable for building and publishing pants components.
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
    classifiers = OrderedSet(standard_classifiers + (additional_classifiers or []))

    notes = PantsReleases.global_instance().notes_for_version(PANTS_SEMVER)

    return PythonArtifact(
        name=name,
        version=VERSION,
        description=description,
        long_description=Path("src/python/pants/ABOUT.rst").read_text() + notes,
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


def contrib_setup_py(name, description, additional_classifiers=None, **kwargs):
    """Creates the setup_py for a pants contrib plugin artifact.

  :param str name: The name of the package; must start with 'pantsbuild.pants.contrib.'.
  :param str description: A brief description of what the plugin provides.
  :param list additional_classifiers: Any additional trove classifiers that apply to the plugin,
                                      see: https://pypi.org/pypi?%3Aaction=list_classifiers
  :param kwargs: Any additional keyword arguments to be passed to `setuptools.setup
                 <https://pythonhosted.org/setuptools/setuptools.html>`_.
  :returns: A setup_py suitable for building and publishing pants components.
  """
    if not name.startswith("pantsbuild.pants.contrib."):
        raise ValueError(
            f"Contrib plugin package names must start with 'pantsbuild.pants.contrib.', given {name}"
        )

    return pants_setup_py(
        name,
        description,
        additional_classifiers=additional_classifiers,
        namespace_packages=["pants", "pants.contrib"],
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
    def _branch_notes(self):
        return self.get_options().branch_notes

    @classmethod
    def _branch_name(cls, version):
        """Defines a mapping between versions and branches.

    In particular, `-dev` suffixed releases always live on master. Any other (modern) release
    lives in a branch.
    """
        suffix = version.public[len(version.base_version) :]
        components = version.base_version.split(".") + [suffix]
        if suffix == "" or suffix.startswith("rc"):
            # An un-suffixed, or suffixed-with-rc version is a release from a stable branch.
            return "{}.{}.x".format(*components[:2])
        elif suffix.startswith(".dev"):
            # Suffixed `dev` release version in master.
            return "master"
        else:
            raise ValueError(f"Unparseable pants version number: {version}")

    def notes_for_version(self, version) -> str:
        """Given the parsed Version of pants, return its release notes.

    TODO: This method should parse out the specific version from the resulting file:
      see https://github.com/pantsbuild/pants/issues/1708
    """
        branch_name = self._branch_name(version)
        branch_notes_file = self._branch_notes.get(branch_name, None)
        if branch_notes_file is None:
            raise ValueError(
                f"Version {version} lives in branch {branch_name}, which is not configured in "
                f"{self._branch_notes}."
            )
        return Path(branch_notes_file).read_text()


class PantsPlugin(PythonLibrary):
    """A pants plugin published by pantsbuild."""

    @classmethod
    def create_setup_py(cls, name, description, additional_classifiers=None):
        return pants_setup_py(
            name,
            description,
            additional_classifiers=additional_classifiers,
            namespace_packages=["pants", "pants.backend"],
        )

    def __init__(
        self,
        address=None,
        payload=None,
        distribution_name=None,
        description=None,
        additional_classifiers=None,
        build_file_aliases=False,
        global_subsystems=False,
        register_goals=False,
        **kwargs,
    ):
        """
    :param str distribution_name: The name of the plugin package; must start with
                                  'pantsbuild.pants.'.
    :param str description: A brief description of what the plugin provides.
    :param list additional_classifiers: Any additional trove classifiers that apply to the plugin,
                                        see: https://pypi.org/pypi?%3Aaction=list_classifiers
    :param bool build_file_aliases: If `True`, register.py:build_file_aliases must be defined and
                                    registers the 'build_file_aliases' 'pantsbuild.plugin'
                                    entrypoint.
    :param bool global_subsystems: If `True`, register.py:global_subsystems must be defined and
                                   registers the 'global_subsystems' 'pantsbuild.plugin' entrypoint.
    :param bool register_goals: If `True`, register.py:register_goals must be defined and
                                registers the 'register_goals' 'pantsbuild.plugin' entrypoint.
    """
        if not distribution_name.startswith("pantsbuild.pants."):
            raise ValueError(
                "Pants plugin package distribution names must start with 'pantsbuild.pants.', given "
                f"{distribution_name}"
            )

        if not os.path.exists(os.path.join(get_buildroot(), address.spec_path, "register.py")):
            raise TargetDefinitionException(
                address.spec_path,
                "A PantsPlugin target must have a register.py file in the same directory.",
            )

        setup_py = self.create_setup_py(
            distribution_name, description, additional_classifiers=additional_classifiers
        )

        super().__init__(address, payload, provides=setup_py, **kwargs)

        if build_file_aliases or register_goals or global_subsystems:
            module = os.path.relpath(address.spec_path, self.target_base).replace(os.sep, ".")
            entrypoints = []
            if build_file_aliases:
                entrypoints.append(f"build_file_aliases = {module}.register:build_file_aliases")
            if register_goals:
                entrypoints.append(f"register_goals = {module}.register:register_goals")
            if global_subsystems:
                entrypoints.append(f"global_subsystems = {module}.register:global_subsystems")
            entry_points = {"pantsbuild.plugin": entrypoints}

            setup_py.setup_py_keywords["entry_points"] = entry_points
            self.mark_invalidation_hash_dirty()  # To pickup the PythonArtifact (setup_py) changes.


class ContribPlugin(PantsPlugin):
    """A contributed pants plugin published by pantsbuild."""

    @classmethod
    def create_setup_py(cls, name, description, additional_classifiers=None):
        return contrib_setup_py(name, description, additional_classifiers=additional_classifiers)


def global_subsystems():
    return {PantsReleases}


def build_file_aliases():
    return BuildFileAliases(
        objects={"pants_setup_py": pants_setup_py, "contrib_setup_py": contrib_setup_py},
        targets={"pants_plugin": PantsPlugin, "contrib_plugin": ContribPlugin},
    )
