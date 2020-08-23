# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from functools import partial
from pathlib import Path
from textwrap import dedent
from typing import List, Optional, Tuple

from fix_deprecated_globs_usage import SCRIPT_RESTRICTIONS, generate_possibly_new_build, warning_msg

from pants.util.contextutil import temporary_dir

Result = Optional[List[str]]


def run_on_build_file(content: str) -> Tuple[Result, Path]:
    with temporary_dir() as tmpdir:
        build = Path(tmpdir, "BUILD")
        build.write_text(content)
        result = generate_possibly_new_build(build)
    return result, build


def assert_rewrite(
    *, original: str, expected: str, include_field_after_sources: bool = True
) -> None:
    template = dedent(
        """\
        # A stray comment

        python_library(
          name="lib",
          {sources_field}
          {dependencies_field}
        )

        python_binary(
          name="bin",
          dependencies=[
            ':lib',
          ],
        )
        """
    )
    dependencies_field = (
        dedent(
            """\
            dependencies=[
              'src/python/pants/util',
            ],
            """
        )
        if include_field_after_sources
        else ""
    )
    result, _ = run_on_build_file(
        template.format(sources_field=original, dependencies_field=dependencies_field),
    )
    if original == expected:
        assert result is None
    else:
        assert (
            result
            == template.format(
                sources_field=expected, dependencies_field=dependencies_field
            ).splitlines()
        )


def assert_warning_raised(
    caplog,
    *,
    warning_num: int,
    build_file_content: str,
    line_number: int,
    field_name: str,
    replacement: str,
    script_restriction: str,
) -> None:
    result, build = run_on_build_file(build_file_content)
    assert result is None  # i.e., the script will not change the BUILD
    assert caplog.records[warning_num].msg == warning_msg(
        build_file=build,
        lineno=line_number,
        field_name=field_name,
        replacement=replacement,
        script_restriction=script_restriction,
    )


def test_no_op_when_already_valid() -> None:
    valid_entries = [
        "sources=['foo.py'],",
        "sources=['!ignore.py'],",
        "sources=[],",
        "sources=['foo.py', '!ignore.py'],",
    ]
    for entry in valid_entries:
        assert_rewrite(original=entry, expected=entry)


def test_includes() -> None:
    assert_rewrite(original="sources=globs(),", expected="sources=[],")
    assert_rewrite(original="sources=zglobs(),", expected="sources=[],")
    assert_rewrite(original="sources=globs('foo.py'),", expected="sources=['foo.py'],")
    assert_rewrite(original="sources=zglobs('foo.py'),", expected="sources=['foo.py'],")
    assert_rewrite(
        original="sources=globs('foo.py', 'bar.py'),", expected="sources=['foo.py', 'bar.py'],"
    )
    assert_rewrite(
        original="sources=zglobs('foo.py', 'bar.py'),", expected="sources=['foo.py', 'bar.py'],"
    )


def test_excludes() -> None:
    assert_rewrite(original="sources=globs(exclude=[]),", expected="sources=[],")

    # `exclude` elements are strings
    assert_rewrite(
        original="sources=globs(exclude=['ignore.py']),", expected="sources=['!ignore.py'],"
    )
    assert_rewrite(
        original="sources=globs(exclude=['ignore.py', 'ignore2.py']),",
        expected="sources=['!ignore.py', '!ignore2.py'],",
    )

    # `exclude` elements are globs
    assert_rewrite(
        original="sources=globs(exclude=[globs('ignore.py')]),", expected="sources=['!ignore.py'],",
    )
    assert_rewrite(
        original="sources=globs(exclude=[globs('ignore.py'), globs('ignore2.py')]),",
        expected="sources=['!ignore.py', '!ignore2.py'],",
    )

    # `exclude` elements are lists
    assert_rewrite(
        original="sources=globs(exclude=[['ignore.py']]),", expected="sources=['!ignore.py'],"
    )
    assert_rewrite(
        original="sources=globs(exclude=[[globs('ignore.py')]]),",
        expected="sources=['!ignore.py'],",
    )

    # `exclude` elements are all of the above
    assert_rewrite(
        original="sources=globs(exclude=['ignore1.py', globs('ignore2.py'), ['ignore3.py'], [globs('ignore4.py')]]),",
        expected="sources=['!ignore1.py', '!ignore2.py', '!ignore3.py', '!ignore4.py'],",
    )

    # check that `exclude` plays nicely with includes
    assert_rewrite(
        original="sources=globs('foo.py', 'bar.py', exclude=['ignore1.py', 'ignore2.py']),",
        expected="sources=['foo.py', 'bar.py', '!ignore1.py', '!ignore2.py'],",
    )


def test_normalizes_rglobs() -> None:
    # Expand when the path component starts with a `*`
    assert_rewrite(original="sources=rglobs('*'),", expected="sources=['**/*'],")
    assert_rewrite(original="sources=rglobs('*.txt'),", expected="sources=['**/*.txt'],")
    assert_rewrite(original="sources=rglobs('test/*.txt'),", expected="sources=['test/**/*.txt'],")
    assert_rewrite(original="sources=rglobs('*/*/*.txt'),", expected="sources=['**/*/*/**/*.txt'],")

    # Don't expand in these cases
    assert_rewrite(original="sources=rglobs('foo.py'),", expected="sources=['foo.py'],")
    assert_rewrite(original="sources=rglobs('test_*'),", expected="sources=['test_*'],")
    assert_rewrite(original="sources=rglobs('**/*'),", expected="sources=['**/*'],")

    # Check the intersection with the `exclude` clause
    assert_rewrite(
        original="sources=rglobs('foo.py', exclude=['*']),", expected="sources=['foo.py', '!*'],",
    )
    assert_rewrite(
        original="sources=globs('foo.py', exclude=[rglobs('*')]),",
        expected="sources=['foo.py', '!**/*'],",
    )


def test_correctly_formats_rewrite() -> None:
    # Preserve the original `sources` prefix, including whitespace
    assert_rewrite(original="sources=globs('foo.py'),", expected="sources=['foo.py'],")
    assert_rewrite(original="sources = globs('foo.py'),", expected="sources = ['foo.py'],")
    assert_rewrite(original="sources =globs('foo.py'),", expected="sources =['foo.py'],")
    assert_rewrite(original="sources= globs('foo.py'),", expected="sources= ['foo.py'],")
    assert_rewrite(original="sources  = globs('foo.py'),", expected="sources  = ['foo.py'],")
    assert_rewrite(original="sources =  globs('foo.py'),", expected="sources =  ['foo.py'],")
    assert_rewrite(original="  sources=globs('foo.py'),", expected="  sources=['foo.py'],")

    # Strip stray trailing whitespace
    assert_rewrite(original="sources=globs('foo.py'),      ", expected="sources=['foo.py'],")

    # Preserve whether the original used single quotes or double quotes
    assert_rewrite(original="""sources=globs("foo.py"),""", expected="""sources=["foo.py"],""")
    assert_rewrite(
        original="""sources=globs("double.py", "foo.py", 'single.py'),""",
        expected="""sources=["double.py", "foo.py", "single.py"],""",
    )

    # Always use a trailing comma
    assert_rewrite(
        original="sources=globs('foo.py')",
        expected="sources=['foo.py'],",
        include_field_after_sources=False,
    )

    # Maintain insertion order for includes
    assert_rewrite(
        original="sources=globs('dog.py', 'cat.py'),", expected="sources=['dog.py', 'cat.py'],",
    )


def test_warns_when_sources_shares_a_line(caplog) -> None:
    assert_warning = partial(
        assert_warning_raised,
        caplog,
        field_name="sources",
        replacement="['foo.py']",
        script_restriction=SCRIPT_RESTRICTIONS["sources_must_be_distinct_line"],
    )
    assert_warning(
        build_file_content="files(sources=globs('foo.py'))", warning_num=0, line_number=1,
    )
    assert_warning(
        build_file_content=dedent(
            """\
            files(
              name='bad', sources=globs('foo.py'),
            )
            """
        ),
        warning_num=1,
        line_number=2,
    )


def test_warns_when_sources_is_multiline(caplog) -> None:
    assert_warning = partial(
        assert_warning_raised,
        caplog,
        field_name="sources",
        replacement='["foo.py", "bar.py"]',
        script_restriction=SCRIPT_RESTRICTIONS["sources_must_be_single_line"],
        line_number=3,
    )
    assert_warning(
        build_file_content=dedent(
            """\
            files(
              name='bad',
              sources=globs(
                "foo.py",
                "bar.py",
              ),
            )
            """
        ),
        warning_num=0,
        # We can't easily infer whether to use single vs. double quotes
        replacement='["foo.py", "bar.py"]',
    )
    assert_warning(
        build_file_content=dedent(
            """\
            files(
              name='bad',
              sources=globs('foo.py',
                            'bar.py'),
            )
            """
        ),
        warning_num=1,
        replacement="['foo.py', 'bar.py']",
    )


def test_warns_on_comments(caplog) -> None:
    assert_warning_raised(
        caplog,
        build_file_content=dedent(
            """\
            files(
              sources=globs('foo.py'),  # a comment
            )
            """
        ),
        warning_num=0,
        line_number=2,
        replacement="['foo.py']",
        field_name="sources",
        script_restriction=SCRIPT_RESTRICTIONS["no_comments"],
    )


def test_warns_on_bundles(caplog) -> None:
    def assert_no_op(build_file_content: str) -> None:
        result, _ = run_on_build_file(build_file_content)
        assert result is None

    assert_no_op(
        dedent(
            """\
            jvm_app(
              bundles=[],
            )
            """
        )
    )
    assert_no_op(
        dedent(
            """\
            jvm_app(
              bundles=[
                bundle(fileset=[]),
              ],
            )
            """
        )
    )
    assert_no_op(
        dedent(
            """\
            jvm_app(
              bundles=[
                bundle(fileset=['foo.java', '!ignore.java']),
              ],
            )
            """
        )
    )

    assert_warning_raised(
        caplog,
        build_file_content=dedent(
            """\
            jvm_app(
              bundles=[
                bundle(fileset=globs('foo.java')),
              ],
            )
            """
        ),
        warning_num=0,
        field_name="bundle(fileset=)",
        line_number=3,
        replacement="['foo.java']",
        script_restriction=SCRIPT_RESTRICTIONS["no_bundles"],
    )

    def check_multiple_bad_bundle_entries(
        build_file_content: str,
        warning_slice: slice,
        *,
        replacements_and_line_numbers: List[Tuple[str, int]],
    ) -> None:
        result, build = run_on_build_file(build_file_content)
        assert result is None
        for record, replacement_and_line_number in zip(
            caplog.records[warning_slice], replacements_and_line_numbers
        ):
            replacement, line_number = replacement_and_line_number
            assert record.message == warning_msg(
                build_file=build,
                lineno=line_number,
                field_name="bundle(fileset=)",
                replacement=replacement,
                script_restriction=SCRIPT_RESTRICTIONS["no_bundles"],
            )

    check_multiple_bad_bundle_entries(
        dedent(
            """\
            jvm_app(
              bundles=[
                bundle(fileset=globs('foo.java')),
                bundle(fileset=globs('bar.java')),
              ],
            )
            """
        ),
        warning_slice=slice(1, 3),
        replacements_and_line_numbers=[("['foo.java']", 3), ("['bar.java']", 4)],
    )
    check_multiple_bad_bundle_entries(
        dedent(
            """\
            jvm_app(
              bundles=[bundle(fileset=globs('foo.java')), bundle(fileset=globs('bar.java'))],
            )
            """
        ),
        warning_slice=slice(3, 5),
        replacements_and_line_numbers=[("['foo.java']", 2), ("['bar.java']", 2)],
    )


def test_warns_on_variables(caplog) -> None:
    result, build = run_on_build_file(
        dedent(
            """\
            files(
              sources=globs(VARIABLE, VAR2),
            )
            """
        )
    )
    assert result is None
    assert f"Could not parse the globs in {build} at line 2." in caplog.records[0].message

    result, build = run_on_build_file(
        dedent(
            """\
            files(
              sources=globs('foo.py', exclude=[VAR1, [VAR2], glob(VAR3)]),
            )
            """
        )
    )
    assert result is None
    assert f"Could not parse the exclude globs in {build} at line 2." in caplog.records[1].message
