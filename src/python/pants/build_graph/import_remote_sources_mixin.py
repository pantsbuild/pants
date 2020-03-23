# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod

from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.target import Target
from pants.util.memo import memoized_property
from pants.util.meta import classproperty
from pants.util.objects import TypeConstraintError


class ImportRemoteSourcesMixin(Target, metaclass=ABCMeta):
    """A Target Mixin to be used when a target declares another target type to be imported."""

    class ExpectedAddressError(AddressLookupError):
        """Thrown upon attempting to resolved an object that is not an address."""

    class UnresolvedImportError(AddressLookupError):
        """Raised when an imported target cannot be resolved."""

    class WrongTargetTypeError(AddressLookupError):
        """Thrown if the wrong type of target is encountered."""

    @classproperty
    @abstractmethod
    def expected_target_constraint(cls):
        """
        :returns: A type constraint which is used to validate the targets containing remote sources,
                  specified `imported_target_kwargs_field` in a BUILD file.
        :rtype: TypeConstraint
        """

    @classproperty
    @abstractmethod
    def imported_target_kwargs_field(cls):
        """
        :returns: string representing the keyword argument of an uninitialized target representing
                  source target specs to be imported.
        :rtype: str
        """

    @classproperty
    @abstractmethod
    def imported_target_payload_field(cls):
        """
        :returns: string representing the payload field of an already-initialized target containing
                  source target specs to be imported.
        :rtype: str
        """

    @classmethod
    def imported_target_specs(cls, kwargs=None, payload=None):
        """
        :param kwargs: A kwargs dict representing Target.__init__(**kwargs) (Optional).
        :param payload: A Payload object representing the Target.__init__(payload=...) param.  (Optional).
        :returns: list of target specs to be imported.
        :rtype: list of str
        """
        if kwargs is not None:
            assert payload is None, "may not provide both kwargs and payload"
            field = cls.imported_target_kwargs_field
            target_representation = kwargs
        else:
            assert payload is not None, "must provide either kwargs or payload"
            field = cls.imported_target_payload_field
            target_representation = payload.as_dict()

        specs = []
        for item in target_representation.get(field, ()):
            if not isinstance(item, str):
                raise cls.ExpectedAddressError(
                    "expected imports to contain string addresses, got {obj} (type: {found_class}) instead.".format(
                        obj=item, found_class=type(item).__name__
                    )
                )
            specs.append(item)

        return specs

    @memoized_property
    def imported_targets(self):
        """
        :returns: target instances for specs referenced by imported_target_specs.
        :rtype: list of Target
        """
        libs = []
        for spec in self.imported_target_specs(payload=self.payload):
            resolved_target = self._build_graph.get_target_from_spec(
                spec, relative_to=self.address.spec_path
            )
            if not resolved_target:
                raise self.UnresolvedImportError(
                    "Could not find target {spec} referenced from {relative_to}".format(
                        spec=spec, relative_to=self.address.spec
                    )
                )
            try:
                libs.append(self.expected_target_constraint.validate_satisfied_by(resolved_target))
            except TypeConstraintError as e:
                raise self.WrongTargetTypeError(
                    "Wrong target type {spec} referenced from remote sources target {relative_to}: {err}".format(
                        spec=spec, relative_to=self.address.spec, err=str(e)
                    ),
                    e,
                )
        return libs

    @classmethod
    def compute_dependency_address_specs(cls, kwargs=None, payload=None):
        """Tack imported_target_specs onto the traversable_specs generator for this target."""
        for address_spec in super().compute_dependency_address_specs(kwargs, payload):
            yield address_spec

        imported_target_specs = cls.imported_target_specs(kwargs=kwargs, payload=payload)
        for address_spec in imported_target_specs:
            yield address_spec
