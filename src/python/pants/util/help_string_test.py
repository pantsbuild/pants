# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.util.help_string import help_string_factory


def test_help_string():

    F = help_string_factory(locals())

    class Demo:
        a = F("Yes! {Demo.b}")
        b = F("I am {Demo.c}!")
        c = "invincible"

    locals()  # `globals` updates automatically, `locals` does not
    assert Demo.a == "Yes! I am invincible!"


def test_help_string_mutual_references():

    F = help_string_factory(locals())

    class FieldA:
        alias = "field_a"
        help = F("Does a thing involving `{FieldB.alias}`.")

    class FieldB:
        alias = "field_b"
        help = F("Provides a thing for `{FieldA.alias}` to use.")

    locals()  # `globals` updates automatically, `locals` does not
    assert FieldA.help == f"Does a thing involving `{FieldB.alias}`."
    assert FieldB.help == f"Provides a thing for `{FieldA.alias}` to use."
