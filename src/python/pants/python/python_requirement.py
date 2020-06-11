# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable, Optional, Tuple, Union

from pkg_resources import Requirement


class PythonRequirement:
    """A Pants wrapper around pkg_resources.Requirement.

    Describes an external dependency as understood by `pip`. It takes a single non-keyword argument
    of the `Requirement`-style string, e.g.

        python_requirement('django-celery')
        python_requirement('tornado==2.2')
        python_requirement('kombu>=2.1.1,<3.0')

    Pants resolves the dependency _and_ its transitive closure*. For example, `django-celery` also
    pulls down its dependencies: `celery>=2.5.1`, `django-picklefield>=0.2.0`, `ordereddict`,
    `python-dateutil`, `kombu>=2.1.1,<3.0`, `anyjson>=0.3.1`, `importlib`, and `amqplib>=1.0`.

    To let other Targets depend on this `python_requirement`, put it in a
    `python_requirement_library`.

    You may specify which modules the requirement provides through the `modules` parameter. If
    unspecified, it will default to the name of the requirement, normalized to comply with Python
    module names. This setting is important for Pants to know how to convert your import
    statements back into your dependencies. For example:

        python_requirement('ansicolors==1.0.0', modules=['colors'])
        python_requirement('Django>2.0')  # Defaults to `modules=['django']`.

    :API: public
    """

    def __init__(
        self,
        requirement: Union[str, Requirement],
        name=None,
        repository=None,
        use_2to3=False,
        compatibility=None,
        *,
        modules: Optional[Iterable[str]] = None,
    ) -> None:
        # TODO(wickman) Allow PythonRequirements to be specified using pip-style vcs or url
        # identifiers, e.g. git+https or just http://...
        self._requirement = (
            requirement if isinstance(requirement, Requirement) else Requirement.parse(requirement)
        )
        self._repository = repository
        self._name = name or self._requirement.project_name
        self._use_2to3 = use_2to3
        self.compatibility = compatibility or [""]
        self._modules = (
            tuple(modules)
            if modules
            else (self._requirement.project_name.lower().replace("-", "_"),)
        )

    def should_build(self, python, platform):
        """
        :API: public
        """
        return True

    @property
    def use_2to3(self):
        """
        :API: public
        """
        return self._use_2to3

    @property
    def repository(self):
        """
        :API: public
        """
        return self._repository

    @property
    def modules(self) -> Tuple[str, ...]:
        """The top-level modules that this requirement provides.

        For example, `ansicolors` provides the `colors` module.

        :API: public
        """
        return self._modules

    # duck-typing Requirement interface for Resolver, since Requirement cannot be
    # subclassed (curses!)
    @property
    def key(self):
        """
        :API: public
        """
        return self._requirement.key

    @property
    def extras(self):
        """
        :API: public
        """
        return self._requirement.extras

    @property
    def specs(self):
        """
        :API: public
        """
        return self._requirement.specs

    @property
    def project_name(self) -> str:
        """
        :API: public
        """
        return self._requirement.project_name

    @property
    def requirement(self):
        """
        :API: public
        """
        return self._requirement

    def __contains__(self, item):
        return item in self._requirement

    def cache_key(self):
        """
        :API: public
        """
        return str(self._requirement)

    def __repr__(self):
        return f"PythonRequirement({self._requirement})"
