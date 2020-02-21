# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.test_base import TestBase
from pants.util.objects import Exactly, SubclassesOf, SuperclassesOf, TypeConstraintError


class TypeConstraintTestBase(TestBase):
    class A:
        def __repr__(self):
            return f"{type(self).__name__}()"

        def __str__(self):
            return f"(str form): {repr(self)}"

        def __eq__(self, other):
            return type(self) == type(other)

    class B(A):
        pass

    class C(B):
        pass

    class BPrime(A):
        pass


class SuperclassesOfTest(TypeConstraintTestBase):
    def test_none(self):
        with self.assertRaisesWithMessage(ValueError, "Must supply at least one type"):
            SubclassesOf()

    def test_str_and_repr(self):
        superclasses_of_b = SuperclassesOf(self.B)
        self.assertEqual("SuperclassesOf(B)", str(superclasses_of_b))
        self.assertEqual("SuperclassesOf(B)", repr(superclasses_of_b))

        superclasses_of_multiple = SuperclassesOf(self.A, self.B)
        self.assertEqual("SuperclassesOf(A or B)", str(superclasses_of_multiple))
        self.assertEqual("SuperclassesOf(A, B)", repr(superclasses_of_multiple))

    def test_single(self):
        superclasses_of_b = SuperclassesOf(self.B)
        self.assertTrue(superclasses_of_b.satisfied_by(self.A()))
        self.assertTrue(superclasses_of_b.satisfied_by(self.B()))
        self.assertFalse(superclasses_of_b.satisfied_by(self.BPrime()))
        self.assertFalse(superclasses_of_b.satisfied_by(self.C()))

    def test_multiple(self):
        superclasses_of_a_or_b = SuperclassesOf(self.A, self.B)
        self.assertTrue(superclasses_of_a_or_b.satisfied_by(self.A()))
        self.assertTrue(superclasses_of_a_or_b.satisfied_by(self.B()))
        self.assertFalse(superclasses_of_a_or_b.satisfied_by(self.BPrime()))
        self.assertFalse(superclasses_of_a_or_b.satisfied_by(self.C()))

    def test_validate(self):
        superclasses_of_a_or_b = SuperclassesOf(self.A, self.B)
        self.assertEqual(self.A(), superclasses_of_a_or_b.validate_satisfied_by(self.A()))
        self.assertEqual(self.B(), superclasses_of_a_or_b.validate_satisfied_by(self.B()))
        with self.assertRaisesWithMessage(
            TypeConstraintError,
            "value C() (with type 'C') must satisfy this type constraint: SuperclassesOf(A or B).",
        ):
            superclasses_of_a_or_b.validate_satisfied_by(self.C())


class ExactlyTest(TypeConstraintTestBase):
    def test_none(self):
        with self.assertRaisesWithMessage(ValueError, "Must supply at least one type"):
            Exactly()

    def test_single(self):
        exactly_b = Exactly(self.B)
        self.assertFalse(exactly_b.satisfied_by(self.A()))
        self.assertTrue(exactly_b.satisfied_by(self.B()))
        self.assertFalse(exactly_b.satisfied_by(self.BPrime()))
        self.assertFalse(exactly_b.satisfied_by(self.C()))

    def test_multiple(self):
        exactly_a_or_b = Exactly(self.A, self.B)
        self.assertTrue(exactly_a_or_b.satisfied_by(self.A()))
        self.assertTrue(exactly_a_or_b.satisfied_by(self.B()))
        self.assertFalse(exactly_a_or_b.satisfied_by(self.BPrime()))
        self.assertFalse(exactly_a_or_b.satisfied_by(self.C()))

    def test_disallows_unsplatted_lists(self):
        with self.assertRaisesWithMessage(TypeError, "Supplied types must be types. ([1],)"):
            Exactly([1])

    def test_str_and_repr(self):
        exactly_b = Exactly(self.B)
        self.assertEqual("Exactly(B)", str(exactly_b))
        self.assertEqual("Exactly(B)", repr(exactly_b))

        exactly_multiple = Exactly(self.A, self.B)
        self.assertEqual("Exactly(A or B)", str(exactly_multiple))
        self.assertEqual("Exactly(A, B)", repr(exactly_multiple))

    def test_checking_via_bare_type(self):
        self.assertTrue(Exactly(self.B).satisfied_by_type(self.B))
        self.assertFalse(Exactly(self.B).satisfied_by_type(self.C))

    def test_validate(self):
        exactly_a_or_b = Exactly(self.A, self.B)
        self.assertEqual(self.A(), exactly_a_or_b.validate_satisfied_by(self.A()))
        self.assertEqual(self.B(), exactly_a_or_b.validate_satisfied_by(self.B()))
        with self.assertRaisesWithMessage(
            TypeConstraintError,
            "value C() (with type 'C') must satisfy this type constraint: Exactly(A or B).",
        ):
            exactly_a_or_b.validate_satisfied_by(self.C())


class SubclassesOfTest(TypeConstraintTestBase):
    def test_none(self):
        with self.assertRaisesWithMessage(ValueError, "Must supply at least one type"):
            SubclassesOf()

    def test_str_and_repr(self):
        subclasses_of_b = SubclassesOf(self.B)
        self.assertEqual("SubclassesOf(B)", str(subclasses_of_b))
        self.assertEqual("SubclassesOf(B)", repr(subclasses_of_b))

        subclasses_of_multiple = SubclassesOf(self.A, self.B)
        self.assertEqual("SubclassesOf(A or B)", str(subclasses_of_multiple))
        self.assertEqual("SubclassesOf(A, B)", repr(subclasses_of_multiple))

    def test_single(self):
        subclasses_of_b = SubclassesOf(self.B)
        self.assertFalse(subclasses_of_b.satisfied_by(self.A()))
        self.assertTrue(subclasses_of_b.satisfied_by(self.B()))
        self.assertFalse(subclasses_of_b.satisfied_by(self.BPrime()))
        self.assertTrue(subclasses_of_b.satisfied_by(self.C()))

    def test_multiple(self):
        subclasses_of_b_or_c = SubclassesOf(self.B, self.C)
        self.assertTrue(subclasses_of_b_or_c.satisfied_by(self.B()))
        self.assertTrue(subclasses_of_b_or_c.satisfied_by(self.C()))
        self.assertFalse(subclasses_of_b_or_c.satisfied_by(self.BPrime()))
        self.assertFalse(subclasses_of_b_or_c.satisfied_by(self.A()))

    def test_validate(self):
        subclasses_of_a_or_b = SubclassesOf(self.A, self.B)
        self.assertEqual(self.A(), subclasses_of_a_or_b.validate_satisfied_by(self.A()))
        self.assertEqual(self.B(), subclasses_of_a_or_b.validate_satisfied_by(self.B()))
        self.assertEqual(self.C(), subclasses_of_a_or_b.validate_satisfied_by(self.C()))
        with self.assertRaisesWithMessage(
            TypeConstraintError,
            "value 1 (with type 'int') must satisfy this type constraint: SubclassesOf(A or B).",
        ):
            subclasses_of_a_or_b.validate_satisfied_by(1)
