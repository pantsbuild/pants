# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
from dataclasses import dataclass
from textwrap import dedent

import pytest

from pants.util.frozendict import FrozenDict
from pants.util.strutil import (
    Simplifier,
    bullet_list,
    comma_separated_list,
    docstring,
    ensure_binary,
    ensure_text,
    first_paragraph,
    fmt_memory_size,
    hard_wrap,
    path_safe,
    pluralize,
    softwrap,
    stable_hash,
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
    assert "1 dependency" == pluralize(1, "dependency")
    assert "2 dependencies" == pluralize(2, "dependency")


def test_comma_separated_list() -> None:
    assert "" == comma_separated_list([])
    assert "foo" == comma_separated_list(["foo"])
    assert "salt and pepper" == comma_separated_list(["salt", "pepper"])
    assert "snap, crackle, and pop" == comma_separated_list(["snap", "crackle", "pop"])


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
            Would reformat /private/var/folders/sx/pdpbqz4x5cscn9hhfpbsbqvm0000gn/T/pants-sandbox-3zt5Ph/src/python/example.py
            Would reformat /var/folders/sx/pdpbqz4x5cscn9hhfpbsbqvm0000gn/T/pants-sandbox-OCnquv/test.py
            Would reformat /custom-tmpdir/pants-sandbox-7zt4pH/custom_tmpdir.py

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

    # A subdir must be prefixed with `pants-sandbox-`, then some characters after it.
    assert (
        strip_v2_chroot_path("/var/pants_sandbox_OCnquv/test.py")
        == "/var/pants_sandbox_OCnquv/test.py"
    )
    assert (
        strip_v2_chroot_path("/var/pants_sandboxOCnquv/test.py")
        == "/var/pants_sandboxOCnquv/test.py"
    )
    assert strip_v2_chroot_path("/var/pants-sandbox/test.py") == "/var/pants-sandbox/test.py"

    # Our heuristic requires absolute paths.
    assert (
        strip_v2_chroot_path("var/pants-sandbox-OCnquv/test.py")
        == "var/pants-sandbox-OCnquv/test.py"
    )

    # Confirm we can handle values with no chroot path.
    assert strip_v2_chroot_path("") == ""
    assert strip_v2_chroot_path("hello world") == "hello world"


@pytest.mark.parametrize(
    ("strip_chroot_path", "strip_formatting", "expected"),
    [
        (False, False, "\033[0;31m/var/pants-sandbox-123/red/path.py\033[0m \033[1mbold\033[0m"),
        (False, True, "/var/pants-sandbox-123/red/path.py bold"),
        (True, False, "\033[0;31mred/path.py\033[0m \033[1mbold\033[0m"),
        (True, True, "red/path.py bold"),
    ],
)
def test_simplifier(strip_chroot_path: bool, strip_formatting: bool, expected: str) -> None:
    simplifier = Simplifier(strip_chroot_path=strip_chroot_path, strip_formatting=strip_formatting)
    result = simplifier.simplify(
        b"\033[0;31m/var/pants-sandbox-123/red/path.py\033[0m \033[1mbold\033[0m"
    )
    assert result == expected


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
            "Do you believe in UFOs, astral projections, mental telepathy, ESP, clairvoyance,"
            + " spirit photography, telekinetic movement, full trance mediums, the Loch Ness monster"
            + " and the theory of Atlantis?"
            + "\n\n"
            + "Ah, if there's a steady paycheck in it, I'll believe anything you say."
            + "\n\n"
            + "[From Ghostbusters (1984)]"
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
            "Do you believe in UFOs, astral projections, mental telepathy, ESP, clairvoyance,"
            + " spirit photography, telekinetic movement, full trance mediums, the Loch Ness monster"
            + " and the theory of Atlantis?"
            + "\n\n"
            + "Ah, if there's a steady paycheck in it, I'll believe anything you say."
            + "\n\n"
            + "[From Ghostbusters (1984)]"
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
            + "\n\n"
            + "    UFOs\n"
            + "    astral projections\n"
            + "    mental telepathy\n"
            + "    ...\n"
            + "\n"
            + "Ah, if there's a steady paycheck in it, I'll believe anything you say."
        )
    )
    assert (
        softwrap(
            """
                Do you believe in:
                    UFOs
                    astral projections
                    mental telepathy
                    ...
            """
        )
        == (
            "Do you believe in:"
            + "\n"
            + "    UFOs\n"
            + "    astral projections\n"
            + "    mental telepathy\n"
            + "    ..."
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
            + "    ```\n"
            + "        - Dr. Peter Venkman\n"
            + "        - Dr. Egon Spengler\n"
            + "        - Dr. Raymond Stantz\n"
            + "        - Winston Zeddemore\n"
            + "\n"
            + "        And not really a ghostbuster, but we need to test wrapped indentation\n"
            # No \n at the end of this one
            + "        - Louis (Vinz, Vinz Clortho, Keymaster of Gozer. Volguus Zildrohar, Lord of"
            + " the Sebouillia)\n"
            + "    ```\n"
            + "\nAll here."
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
            + "  * Dr. Peter Venkman\n"
            + "  * Dr. Egon Spengler\n"
            + "  * Dr. Raymond Stantz\n"
            + "\nAll here."
        )
    )
    assert softwrap("A\n\n\nB") == "A\n\nB"
    assert (
        softwrap(
            f"""
                Roll Call:
                {bullet_list(["Dr. Peter Venkman", "Dr. Egon Spengler", "Dr. Raymond Stantz"])}
                All here.
            """
        )
        == (
            "Roll Call:\n"
            + "  * Dr. Peter Venkman\n"
            + "  * Dr. Egon Spengler\n"
            + "  * Dr. Raymond Stantz\n"
            + "All here."
        )
    )
    # This models when we output stdout/stderr. The canonical way to do that is to indent every line
    #   so that softwrap preserves common indentation and the output "looks right"
    stdout = "* Dr. Peter Venkman\n* Dr. Egon Spengler\n* Dr. Raymond Stantz"
    assert (
        softwrap(
            f"""
                Roll Call:
                {textwrap.indent(stdout, " "*2)}
                All here.
            """
        )
        == (
            "Roll Call:\n"
            + "  * Dr. Peter Venkman\n"
            + "  * Dr. Egon Spengler\n"
            + "  * Dr. Raymond Stantz\n"
            + "All here."
        )
    )


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


def test_docstring_decorator() -> None:
    @docstring(f"calc 1 + 1 = {1 + 1}")
    def document_me():
        pass

    assert document_me.__doc__ == "calc 1 + 1 = 2"

    def show_why_this_is_needed() -> None:
        f"""calc 1 + 1 = {1 + 1}"""  # noqa: B021

    with pytest.raises(AssertionError):
        assert show_why_this_is_needed.__doc__ == "calc 1 + 1 = 2"


def test_stable_hash() -> None:
    @dataclass(frozen=True)
    class Data:
        mapping: FrozenDict[str, str]

    data = Data(
        FrozenDict(
            {alpha: alpha.lower() for alpha in [chr(a) for a in range(ord("A"), ord("Z") + 1)]}
        )
    )
    assert stable_hash(data) == "1f2a0caa2588274fa99dc7397c1687dbbe6159be0de646a37ba7af241ecf1add"
