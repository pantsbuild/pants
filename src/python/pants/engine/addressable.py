# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from functools import update_wrapper
from typing import Any, Sequence, Set, Tuple, Type

from pants.base.exceptions import ResolveError
from pants.base.specs import OriginSpec
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.objects import Collection, Resolvable, Serializable
from pants.util.objects import TypeConstraintError


def assert_single_address(addresses: Sequence[Address]) -> None:
    """Assert that exactly one address must be contained in the collection."""
    if len(addresses) == 0:
        raise ResolveError("No targets were matched.")
    if len(addresses) > 1:
        output = "\n  * ".join(address.spec for address in addresses)
        raise ResolveError(
            "Expected a single target, but was given multiple targets.\n\n"
            f"Did you mean one of:\n  * {output}"
        )


class Addresses(Collection[Address]):
    def expect_single(self) -> Address:
        assert_single_address(self.dependencies)
        return self.dependencies[0]


@dataclass(frozen=True)
class AddressWithOrigin:
    """A BuildFileAddress along with the cmd-line spec it was generated from."""

    address: Address
    origin: OriginSpec


class AddressesWithOrigins(Collection[AddressWithOrigin]):
    def expect_single(self) -> AddressWithOrigin:
        assert_single_address(
            [address_with_origin.address for address_with_origin in self.dependencies]
        )
        return self.dependencies[0]


class BuildFileAddresses(Collection[BuildFileAddress]):
    """NB: V2 should generally use Addresses instead of BuildFileAddresses."""


class NotSerializableError(TypeError):
    """Indicates an addressable descriptor is illegally installed in a non-Serializable type."""


class MutationError(AttributeError):
    """Indicates an illegal attempt to mutate an addressable attribute that already has a value."""


class AddressableTypeValidationError(TypeConstraintError):
    """Indicates a value provided to an `AddressableDescriptor` failed to satisfy a type
    constraint."""


class AddressableDescriptor:
    """A data descriptor for fields containing one or more addressable items.

    An addressable descriptor has lifecycle expectations tightly coupled with the contract of
    Serializable objects and the 2-phase hydration of AddressMap.parse, Graph.resolve.

    Decorated accessors are write-once, and then read-only.  They are intended to be written in a
    constructor such that objects containing them have immutable semantics. In other words, the
    descriptor is intended to be used like a type-checked `@property` with possibly lazily resolved
    values.

    The written value is type-checked against a :class:`TypeConstraint` and can only be one of 3
    types:

    1. An opaque string address.
    2. A Resolvable for the address that, when resolved, will meet the type constraint.
    3. A concrete value that meets the type constraint.

    The 1st type, an opaque string address, is also the type associated with the 1st stage of the
    2-stage lifecycle of Serializable objects containing addressable values.  In the second and final
    stage, the Serializable object is re-constructed with addressable values of the second or third
    types; ie: reconstructed with either resolvables or concrete values in place of the first stage
    address.

    Two affordances are made in type constraint handling:

    1. Either a :class:`TypeConstraint` instance can be given if the type constraint is fully known or
       else a type constraint class can be given if the type constraint should apply to the type of
       the enclosing class.  This is useful for declaring an addressable property in a baseclass that
       should be type-constrained based on the type of the derived class.
    2. Decorators for addressables (see `addressable`, `addressable_sequence` and `addressable_dict`)
       allow wrapping of either class functions - typical - or @property descriptors.  The property
       descriptor case sets up an idiom for recursive addressables.  The idiom looks like:

       >>> class Thing(Struct):
       ...   def __init__(self, thing):
       ...     super().__init__()
       ...     self.thing = thing
       ...   @property
       ...   def parent(self):
       ...     '''Return this thing's parent.
       ...
       ...     :rtype: :class:`Thing`
       ...     '''
       ...
       >>> Thing.parent = addressable(Exactly(Thing))(Thing.parent)

    Here the `Thing.parent` property is re-assigned with a type-constrained addressable descriptor
    after the class is defined so the class can be referred to in the type constraint.
    """

    _descriptors: Set[Tuple[Type, str]] = set()

    @classmethod
    def is_addressable(cls, obj: Any, key: str) -> bool:
        """Return `True` if the given attribute of `obj` is an addressable attribute.

        :param obj: The object to inspect.
        :param key: The name of the property on `obj` to check.
        """
        return (type(obj), key) in cls._descriptors

    @classmethod
    def _register(cls, obj, descriptor):
        cls._descriptors.add((type(obj), descriptor._name))

    def __init__(self, name, type_constraint):
        self._name = name
        self._type_constraint = type_constraint

    def __set__(self, instance, value):
        if not Serializable.is_serializable(instance):
            raise NotSerializableError(
                "The addressable descriptor {} can only be applied to methods or "
                "properties of Serializable objects, applied to method {} of "
                "type {}".format(type(self).__name__, self._name, type(instance).__name__)
            )

        instance_dict = instance._asdict()
        if self._name in instance_dict:
            raise MutationError(
                "Attribute {} of {} has already been set to {}, rejecting attempt to "
                "re-set with {}".format(self._name, instance, instance_dict[self._name], value)
            )

        value = self._checked_value(instance, value)

        self._register(instance, self)

        # We mutate the instance dict, which is only OK if used in the conventional idiom of setting
        # the value via this data descriptor in the instance's constructor.
        instance_dict[self._name] = value

    def __get__(self, instance, unused_owner_type=None):
        # We know instance is a Serializable from the type-checking done in set.
        value = instance._asdict()[self._name]
        return self._resolve_value(instance, value)

    def _get_type_constraint(self, instance):
        if inspect.isclass(self._type_constraint):
            return self._type_constraint(type(instance))
        else:
            return self._type_constraint

    def _checked_value(self, instance, value):
        # We allow five forms of value:
        # 0. None.
        # 1. An opaque (to us) address pointing to a value that can be resolved by external
        #    means.
        # 2. A `Resolvable` value that we can lazily resolve and type-check in `__get__`.
        # 3. A concrete instance that meets our type constraint.
        # 4. A dict when our type constraint has exactly one Serializable subject type - we convert the
        #    dict into an instance of that type.
        if value is None:
            return None

        if isinstance(value, (str, Address, Resolvable)):
            return value

        # Support untyped dicts that we deserialize on-demand here into the required type.
        # This feature allows for more brevity in the JSON form (local type inference) and an alternate
        # construction style in the python forms.
        type_constraint = self._get_type_constraint(instance)
        if (
            isinstance(value, dict)
            and len(type_constraint.types) == 1
            and Serializable.is_serializable_type(type_constraint.types[0])
        ):
            if not value:
                # TODO(John Sirois): Is this the right thing to do?  Or should an empty serializable_type
                # be constructed?
                return None  # {} -> None.
            else:
                serializable_type = type_constraint.types[0]
                return serializable_type(**value)

        try:
            return type_constraint.validate_satisfied_by(value)
        except TypeConstraintError as e:
            raise AddressableTypeValidationError(
                "The value for the {} attribute of {} was invalid".format(self._name, instance), e
            )

    def _resolve_value(self, instance, value):
        if not isinstance(value, Resolvable):
            # The value is concrete which means we type-checked on set so no need to do so again, its a
            # raw address string or an instance that satisfies our type constraint.
            return value
        else:
            resolved_value = value.resolve()
            type_constraint = self._get_type_constraint(instance)

            try:
                return type_constraint.validate_satisfied_by(resolved_value)
            except TypeConstraintError as e:
                raise AddressableTypeValidationError(
                    "The value resolved from {} for the {} property of {} was invalid".format(
                        value.address, self._name, instance
                    ),
                    e,
                )


def _addressable_wrapper(addressable_descriptor, type_constraint):
    def wrapper(func):
        # We allow for wrapping property objects to support the following idiom for defining recursive
        # addressables:
        #
        # class Thing(Struct):
        #   def __init__(self, thing):
        #      super().__init__()
        #      self.thing = thing
        #
        #   @property
        #   def parent(self):
        #     """Return this thing's parent.
        #
        #     :rtype: :class:`Thing`
        #     """"
        #
        # Thing.parent = addressable(Exactly(Thing))(Thing.parent)
        func = func.fget if isinstance(func, property) else func

        addressable_accessor = addressable_descriptor(func.__name__, type_constraint)
        return update_wrapper(addressable_accessor, func)

    return wrapper


def addressable(type_constraint):
    """Return an addressable attribute for Serializable classes.

    The attribute should have no implementation (it will be ignored), but can carry a docstring.
    The implementation is provided by this wrapper.  Idiomatic use assigns the value, which can
    either be an opaque address string or a resolved value that meets the type constraint, in the
    constructor::

    >>> class Employee(Serializable):
    ...   def __init__(self, person):
    ...     self.person = person
    ...   @addressable(SubclassesOf(Person))
    ...   def person(self):
    ...     '''The person that is this employee.'''

    Addressable attributes are only assignable once, so this pattern yields an immutable `Employee`
    whose `person` attribute is either a `Person` instance or
    :class:`pants.engine.objects.Resolvable` person or else a string address pointing to one.

    See :class:`AddressableDescriptor` for more details.

    :param type_constraint: The type constraint the value must satisfy.
    :type type_constraint: :class:`TypeConstraint`
    """
    return _addressable_wrapper(AddressableDescriptor, type_constraint)


class AddressableSequence(AddressableDescriptor):
    def _checked_value(self, instance, value):
        if value is None:
            return None

        if not isinstance(value, (list, tuple)):
            raise TypeError(
                "The {} property of {} must be a tuple or list, given {} of type {}".format(
                    self._name, instance, value, type(value).__name__
                )
            )
        return [super(AddressableSequence, self)._checked_value(instance, v) for v in value]

    def _resolve_value(self, instance, value):
        return (
            tuple(super(AddressableSequence, self)._resolve_value(instance, v) for v in value)
            if value
            else ()
        )


def addressable_sequence(type_constraint):
    """Marks a sequence's values as satisfying a given type constraint.

    Some (or all) elements of the sequence may be :class:`pants.engine.objects.Resolvable` elements
    to resolve later.

    See :class:`AddressableDescriptor` for more details.

    :param type_constraint: The type constraint the list's values must all satisfy.
    :type type_constraint: :class:`TypeConstraint`
    """
    return _addressable_wrapper(AddressableSequence, type_constraint)


class AddressableDict(AddressableDescriptor):
    def _checked_value(self, instance, value):
        if value is None:
            return None

        if not isinstance(value, Mapping):
            raise TypeError(
                "The {} property of {} must be a dict, given {} of type {}".format(
                    self._name, instance, value, type(value).__name__
                )
            )
        return {
            k: super(AddressableDict, self)._checked_value(instance, v) for k, v in value.items()
        }

    def _resolve_value(self, instance, value):
        return (
            {k: super(AddressableDict, self)._resolve_value(instance, v) for k, v in value.items()}
            if value
            else {}
        )


def addressable_dict(type_constraint):
    """Marks a dicts's values as satisfying a given type constraint.

    Some (or all) values in the dict may be :class:`pants.engine.objects.Resolvable` values to
    resolve later.

    See :class:`AddressableDescriptor` for more details.

    :param type_constraint: The type constraint the dict's values must all satisfy.
    :type type_constraint: :class:`TypeConstraint`
    """
    return _addressable_wrapper(AddressableDict, type_constraint)


# TODO(John Sirois): Move variants into Address 1st class as part of merging the engine/exp
# into the mainline (if they survive).
# TODO: Variants currently require an explicit name (and thus a `:`) in order to parse correctly.
def strip_variants(address):
    """Return a copy of the given address with the variants (if any) stripped from the name.

    :rtype: :class:`pants.build_graph.address.Address`
    """
    address, _ = parse_variants(address)
    return address


def _extract_variants(address, variants_str):
    """Return the variants (if any) represented by the given variants_str.

    :returns: The variants or else `None` if there are none.
    :rtype: tuple of tuples (key, value) strings
    """

    def entries():
        for entry in variants_str.split(","):
            key, _, value = entry.partition("=")
            if not key or not value:
                raise ValueError("Invalid variants after the @ in: {}".format(address))
            yield (key, value)

    return tuple(entries())


def parse_variants(address):
    target_name, at_sign, variants_str = address.target_name.partition("@")
    if not at_sign:
        return address, None
    variants = _extract_variants(address, variants_str) if variants_str else None
    if isinstance(address, BuildFileAddress):
        normalized_address = BuildFileAddress(rel_path=address.rel_path, target_name=target_name)
    else:
        normalized_address = Address(spec_path=address.spec_path, target_name=target_name)
    return normalized_address, variants
