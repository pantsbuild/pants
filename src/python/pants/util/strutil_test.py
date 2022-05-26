# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.util.strutil import (
    bullet_list,
    ensure_binary,
    ensure_text,
    first_paragraph,
    fmt_memory_size,
    hard_wrap,
    path_safe,
    pluralize,
    softwrap,
    strip_prefix,
    strip_v2_chroot_path,
)


def test_pluralize() -> None:
    assert "1 bat" == pluralize(1, "bat")
    assert "1 boss" == pluralize(1, "boss")
    assert "2 bats" == pluralize(2, "bat")
    assert "2 bosses" == pluralize(2, "boss")
    assert "0 bats" == pluralize(0, "bat")
    assert "0 bosses" == pluralize(0, "boss")


def test_ensure_text() -> None:
    bytes_val = bytes(bytearray([0xE5, 0xBF, 0xAB]))
    assert "快" == ensure_text(bytes_val)
    with pytest.raises(TypeError):
        ensure_text(45)  # type: ignore[arg-type] # intended to fail type check


def test_ensure_binary() -> None:
    unicode_val = "快"
    assert bytearray([0xE5, 0xBF, 0xAB]) == ensure_binary(unicode_val)
    with pytest.raises(TypeError):
        ensure_binary(45)  # type: ignore[arg-type] # intended to fail type check


def test_strip_prefix() -> None:
    assert "testString" == strip_prefix("testString", "//")
    assert "/testString" == strip_prefix("/testString", "//")
    assert "testString" == strip_prefix("//testString", "//")
    assert "/testString" == strip_prefix("///testString", "//")
    assert "//testString" == strip_prefix("////testString", "//")
    assert "test//String" == strip_prefix("test//String", "//")
    assert "testString//" == strip_prefix("testString//", "//")


def test_strip_chroot_path() -> None:
    assert (
        strip_v2_chroot_path(
            dedent(
                """\
            Would reformat /private/var/folders/sx/pdpbqz4x5cscn9hhfpbsbqvm0000gn/T/process-execution3zt5Ph/src/python/example.py
            Would reformat /var/folders/sx/pdpbqz4x5cscn9hhfpbsbqvm0000gn/T/process-executionOCnquv/test.py
            Would reformat /custom-tmpdir/process-execution7zt4pH/custom_tmpdir.py

            Some other output.
            """
            )
        )
        == dedent(
            """\
        Would reformat src/python/example.py
        Would reformat test.py
        Would reformat custom_tmpdir.py

        Some other output.
        """
        )
    )

    # A subdir must be prefixed with `process-execution`, then some characters after it.
    assert (
        strip_v2_chroot_path("/var/process_executionOCnquv/test.py")
        == "/var/process_executionOCnquv/test.py"
    )
    assert (
        strip_v2_chroot_path("/var/process-execution/test.py") == "/var/process-execution/test.py"
    )

    # Our heuristic requires absolute paths.
    assert (
        strip_v2_chroot_path("var/process-executionOCnquv/test.py")
        == "var/process-executionOCnquv/test.py"
    )

    # Confirm we can handle values with no chroot path.
    assert strip_v2_chroot_path("") == ""
    assert strip_v2_chroot_path("hello world") == "hello world"


def test_hard_wrap() -> None:
    assert hard_wrap("Hello world!", width=6) == ["Hello", "world!"]

    # Indents play into the width.
    assert hard_wrap("Hello world!", width=6, indent=2) == ["  Hell", "  o wo", "  rld!"]
    assert hard_wrap("Hello world!", width=8, indent=2) == ["  Hello", "  world!"]

    # Preserve prior newlines.
    assert hard_wrap("- 1\n- 2\n\n") == ["- 1", "- 2", ""]
    assert hard_wrap("Hello world!\n\n- 1 some text\n- 2\n\nHola mundo!", width=6) == [
        "Hello",
        "world!",
        "",
        "- 1",
        "some",
        "text",
        "- 2",
        "",
        "Hola",
        "mundo!",
    ]


def test_first_paragraph() -> None:
    assert (
        first_paragraph(
            dedent(
                """\
            Hello! I'm spread out
            over multiple
               lines.

            Second paragraph.
            """
            )
        )
        == "Hello! I'm spread out over multiple    lines."
    )
    assert first_paragraph("Only one paragraph.") == "Only one paragraph."


def test_path_safe() -> None:
    assert "abcDEF123" == path_safe("abcDEF123")
    assert "CPython>=2.7,<3 (fun times)" == path_safe("CPython>=2.7,<3 (fun times)")
    assert "foo bar_ baz_" == path_safe("foo bar! baz@")


def test_bullet_list() -> None:
    assert bullet_list(["a", "b", "c"]) == (
        """\
  * a
  * b
  * c"""
    )
    assert bullet_list(["a"]) == "  * a"
    assert bullet_list([]) == ""


def test_bullet_list_max_elements() -> None:
    assert bullet_list(list("abcdefg"), 3) == (
        """\
  * a
  * b
  * ... and 5 more"""
    )


def test_softwrap_multiline() -> None:
    assert (
        softwrap("The version of the prior release, e.g. `2.0.0.dev0` or `2.0.0rc1`.")
        == "The version of the prior release, e.g. `2.0.0.dev0` or `2.0.0rc1`."
    )
    # Test with leading backslash
    assert (
        softwrap(
            """\
                Do you believe in UFOs, astral projections, mental telepathy, ESP, clairvoyance,
                spirit photography, telekinetic movement, full trance mediums, the Loch Ness monster
                and the theory of Atlantis?

                Ah, if there's a steady paycheck in it,
                I'll believe anything you say.

                [From
                Ghostbusters (1984)]
            """
        )
        == (
            "Do you believe in UFOs, astral projections, mental telepathy, ESP, clairvoyance, "
            "spirit photography, telekinetic movement, full trance mediums, the Loch Ness monster "
            "and the theory of Atlantis?"
            "\n\n"
            "Ah, if there's a steady paycheck in it, I'll believe anything you say."
            "\n\n"
            "[From Ghostbusters (1984)]"
        )
    )
    # Test without leading backslash
    assert (
        softwrap(
            """
                Do you believe in UFOs, astral projections, mental telepathy, ESP, clairvoyance,
                spirit photography, telekinetic movement, full trance mediums, the Loch Ness monster
                and the theory of Atlantis?

                Ah, if there's a steady paycheck in it,
                I'll believe anything you say.

                [From
                Ghostbusters (1984)]
            """
        )
        == (
            "Do you believe in UFOs, astral projections, mental telepathy, ESP, clairvoyance, "
            "spirit photography, telekinetic movement, full trance mediums, the Loch Ness monster "
            "and the theory of Atlantis?"
            "\n\n"
            "Ah, if there's a steady paycheck in it, I'll believe anything you say."
            "\n\n"
            "[From Ghostbusters (1984)]"
        )
    )
    assert (
        softwrap(
            """
                Do you
                believe in:

                    UFOs
                    astral projections
                    mental telepathy
                    ...

                Ah, if there's a steady paycheck in it,
                I'll believe anything you say.
            """
        )
        == (
            "Do you believe in:"
            "\n\n"
            "    UFOs\n"
            "    astral projections\n"
            "    mental telepathy\n"
            "    ...\n"
            "\n"
            "Ah, if there's a steady paycheck in it, I'll believe anything you say."
        )
    )
    assert (
        softwrap(
            """
                Roll Call:

                    ```
                        - Dr. Peter Venkman
                        - Dr. Egon Spengler
                        - Dr. Raymond Stantz
                        - Winston Zeddemore

                        And not really a ghostbuster, but we need to test wrapped indentation
                        - Louis (Vinz, Vinz Clortho,\
                        Keymaster of Gozer. Volguus Zildrohar, Lord of\
                            the Sebouillia)
                    ```

                All here.
            """
        )
        == (
            "Roll Call:\n\n"
            "    ```\n"
            "        - Dr. Peter Venkman\n"
            "        - Dr. Egon Spengler\n"
            "        - Dr. Raymond Stantz\n"
            "        - Winston Zeddemore\n"
            "\n"
            "        And not really a ghostbuster, but we need to test wrapped indentation\n"
            # No \n at the end of this one
            "        - Louis (Vinz, Vinz Clortho, Keymaster of Gozer. Volguus Zildrohar, Lord of "
            "the Sebouillia)\n"
            "    ```\n"
            "\nAll here."
        )
    )
    assert (
        softwrap(
            f"""
                Roll Call:

                {bullet_list(["Dr. Peter Venkman", "Dr. Egon Spengler", "Dr. Raymond Stantz"])}

                All here.
            """
        )
        == (
            "Roll Call:\n\n"
            "  * Dr. Peter Venkman\n"
            "  * Dr. Egon Spengler\n"
            "  * Dr. Raymond Stantz\n"
            "\nAll here."
        )
    )
    assert softwrap("A\n\n\nB") == "A\n\nB"


_TEST_MEMORY_SIZES_PARAMS = [
    (312, "312B"),
    (1028, "1028B"),
    (2 * 1024, "2KiB"),
    (2 * 1024 * 1024, "2MiB"),
    (4 * 1024 * 1024 * 1024, "4GiB"),
    (2 * 1024 * 1024 * 1024 * 1024, "2048GiB"),
]


@pytest.mark.parametrize("mem_size, expected", _TEST_MEMORY_SIZES_PARAMS)
def test_fmt_memory_sizes(mem_size: int, expected: str) -> None:
    assert fmt_memory_size(mem_size) == expected
