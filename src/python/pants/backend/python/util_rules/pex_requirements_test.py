# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import json
import textwrap
import tomllib

import pytest

from pants.backend.python.subsystems.setup import InvalidLockfileBehavior, PythonSetup
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadataV3
from pants.backend.python.util_rules.pex_requirements import (
    Lockfile,
    ResolveConfig,
    ResolvePexConstraintsFile,
    _pex_lockfile_requirement_count,
    get_metadata,
    is_probably_pex_json_lockfile,
    strip_comments_from_pex_json_lockfile,
    validate_metadata,
)
from pants.core.util_rules.lockfile_metadata import (
    BEGIN_LOCKFILE_HEADER,
    END_LOCKFILE_HEADER,
    InvalidLockfileError,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.testutil.option_util import create_subsystem
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.pip_requirement import PipRequirement
from pants.util.strutil import comma_separated_list

METADATA = PythonLockfileMetadataV3(
    InterpreterConstraints(["==3.8.*"]),
    {PipRequirement.parse("ansicolors"), PipRequirement.parse("requests")},
    manylinux=None,
    requirement_constraints={PipRequirement.parse("abc")},
    only_binary={"bdist"},
    no_binary={"sdist"},
)


def create_python_setup(
    behavior: InvalidLockfileBehavior, *, enable_resolves: bool = True
) -> PythonSetup:
    return create_subsystem(
        PythonSetup,
        invalid_lockfile_behavior=behavior,
        resolves_generate_lockfiles=enable_resolves,
        interpreter_versions_universe=PythonSetup.default_interpreter_universe,
        resolves={"a": "lock.txt"},
        default_resolve="a",
    )


def test_get_metadata() -> None:
    # We don't get metadata if we've been told not to validate it.
    python_setup = create_python_setup(behavior=InvalidLockfileBehavior.ignore)
    metadata = get_metadata(python_setup, b"", None, "dummy", "#")
    assert metadata is None

    python_setup = create_python_setup(behavior=InvalidLockfileBehavior.warn)

    # If we are supposed to validate Pants-generated lockfiles, but there is no header
    # block, then it's not a Pants-generated lockfile, so succeed but return no metadata.
    metadata = get_metadata(python_setup, b"NO HEADER HERE", None, "dummy", "#")
    assert metadata is None

    # If we are supposed to validate Pants-generated lockfiles, and there is a header
    # block, then succeed on valid JSON.
    valid_lock_metadata = json.dumps(
        {
            "valid_for_interpreter_constraints": "dummy",
            "requirements_invalidation_digest": "dummy",
        }
    )
    metadata = get_metadata(
        python_setup,
        f"# {BEGIN_LOCKFILE_HEADER}\n# {valid_lock_metadata}\n# {END_LOCKFILE_HEADER}\n".encode(),
        None,
        "dummy",
        "#",
    )
    assert metadata is not None

    # If we are supposed to validate Pants-generated lockfiles, and there is a header
    # block, then fail on invalid JSON.
    with pytest.raises(InvalidLockfileError):
        get_metadata(
            python_setup,
            f"# {BEGIN_LOCKFILE_HEADER}\n# NOT JSON\n# {END_LOCKFILE_HEADER}\n".encode(),
            None,
            "dummy",
            "#",
        )
    # If we are supposed to validate Pants-generated lockfiles, and there is a header
    # block, then fail on JSON that doesn't have the keys we expect.
    with pytest.raises(InvalidLockfileError):
        get_metadata(
            python_setup,
            f"# {BEGIN_LOCKFILE_HEADER}\n# {{ 'a': 'b' }}\n# {END_LOCKFILE_HEADER}\n".encode(),
            None,
            "dummy",
            "#",
        )


@pytest.mark.parametrize(
    (
        "invalid_reqs,invalid_interpreter_constraints,invalid_constraints_file,invalid_only_binary,"
        + "invalid_no_binary,invalid_manylinux"
    ),
    [
        (
            invalid_reqs,
            invalid_interpreter_constraints,
            invalid_constraints_file,
            invalid_only_binary,
            invalid_no_binary,
            invalid_manylinux,
        )
        for invalid_reqs in (True, False)
        for invalid_interpreter_constraints in (True, False)
        for invalid_constraints_file in (True, False)
        for invalid_only_binary in (True, False)
        for invalid_no_binary in (True, False)
        for invalid_manylinux in (True, False)
        if (
            invalid_reqs
            or invalid_interpreter_constraints
            or invalid_constraints_file
            or invalid_only_binary
            or invalid_no_binary
            or invalid_manylinux
        )
    ],
)
def test_validate_lockfiles(
    invalid_reqs: bool,
    invalid_interpreter_constraints: bool,
    invalid_constraints_file: bool,
    invalid_only_binary: bool,
    invalid_no_binary: bool,
    invalid_manylinux: bool,
    caplog,
) -> None:
    runtime_interpreter_constraints = (
        InterpreterConstraints(["==2.7.*"])
        if invalid_interpreter_constraints
        else METADATA.valid_for_interpreter_constraints
    )
    req_strings = FrozenOrderedSet(
        ["bad-req"] if invalid_reqs else [str(r) for r in METADATA.requirements]
    )
    lockfile = Lockfile(
        url="lock.txt",
        url_description_of_origin="foo",
        resolve_name="a",
    )

    validate_metadata(
        METADATA,
        runtime_interpreter_constraints,
        lockfile,
        req_strings,
        validate_consumed_req_strings=True,
        python_setup=create_python_setup(InvalidLockfileBehavior.warn),
        resolve_config=ResolveConfig(
            indexes=(),
            find_links=(),
            manylinux="not-manylinux" if invalid_manylinux else None,
            constraints_file=ResolvePexConstraintsFile(
                EMPTY_DIGEST,
                "c.txt",
                FrozenOrderedSet(
                    {PipRequirement.parse("xyz" if invalid_constraints_file else "abc")}
                ),
            ),
            no_binary=FrozenOrderedSet(["not-sdist" if invalid_no_binary else "sdist"]),
            only_binary=FrozenOrderedSet(["not-bdist" if invalid_only_binary else "bdist"]),
            overrides=FrozenOrderedSet(),
            excludes=FrozenOrderedSet(),
            sources=FrozenOrderedSet(),
            path_mappings=(),
            lock_style="universal",
            complete_platforms=(),
            uploaded_prior_to=None,
        ),
    )

    def contains(msg: str, if_: bool = True) -> None:
        assert (msg in caplog.text) is if_

    reqs_desc = comma_separated_list(f"`{rs}`" for rs in req_strings)
    contains(
        f"You are consuming {reqs_desc} from the `a` lockfile at lock.txt with incompatible inputs"
    )
    contains(
        "The lockfile does not provide all the necessary requirements",
        if_=invalid_reqs,
    )
    contains(
        "The requirements not provided by the `a` resolve are:\n  ['bad-req']",
        if_=invalid_reqs,
    )

    contains("The inputs use interpreter constraints", if_=invalid_interpreter_constraints)

    contains("The constraints file at c.txt has changed", if_=invalid_constraints_file)
    contains("The `only_binary` arguments have changed", if_=invalid_only_binary)
    contains("The `no_binary` arguments have changed", if_=invalid_no_binary)
    contains("The `manylinux` argument has changed", if_=invalid_manylinux)

    contains("pants generate-lockfiles --resolve=a`")


def test_is_probably_pex_json_lockfile():
    def is_pex(lock: str) -> bool:
        return is_probably_pex_json_lockfile(lock.encode())

    for s in (
        "{}",
        textwrap.dedent(
            """\
            // Special comment
            {}
            """
        ),
        textwrap.dedent(
            """\
            // Next line has extra space
             {"key": "val"}
            """
        ),
        textwrap.dedent(
            """\
            {
                "key": "val",
            }
            """
        ),
    ):
        assert is_pex(s)

    for s in (
        "",
        "# foo",
        "# {",
        "cheesey",
        "cheesey==10.0",
        textwrap.dedent(
            """\
            # Special comment
            cheesey==10.0
            """
        ),
    ):
        assert not is_pex(s)


def test_strip_comments_from_pex_json_lockfile() -> None:
    def assert_stripped(lock: str, expected: str) -> None:
        assert strip_comments_from_pex_json_lockfile(lock.encode()).decode() == expected

    assert_stripped("{}", "{}")
    assert_stripped(
        textwrap.dedent(
            """\
            { // comment
                "key": "foo",
            }
            """
        ),
        textwrap.dedent(
            """\
            { // comment
                "key": "foo",
            }"""
        ),
    )
    assert_stripped(
        textwrap.dedent(
            """\
            // header
               // more header
              {
                "key": "foo",
            }
            // footer
            """
        ),
        textwrap.dedent(
            """\
              {
                "key": "foo",
            }"""
        ),
    )


def test_pex_lockfile_requirement_count() -> None:
    assert _pex_lockfile_requirement_count(b"empty") == 2
    assert (
        _pex_lockfile_requirement_count(
            textwrap.dedent(
                """\
            {
              "allow_builds": true,
              "allow_prereleases": false,
              "allow_wheels": true,
              "build_isolation": true,
              "constraints": [],
              "locked_resolves": [
                {
                  "locked_requirements": [
                    {
                      "artifacts": [
                        {
                          "algorithm": "sha256",
                          "hash": "00d2dde5a675579325902536738dd27e4fac1fd68f773fe36c21044eb559e187",
                          "url": "https://files.pythonhosted.org/packages/53/18/a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/ansicolors-1.1.8-py2.py3-none-any.whl"
                        }
                      ],
                      "project_name": "ansicolors",
                      "requires_dists": [],
                      "requires_python": null,
                      "version": "1.1.8"
                    }
                  ],
                  "platform_tag": [
                    "cp39",
                    "cp39",
                    "macosx_11_0_arm64"
                  ]
                }
              ],
              "pex_version": "2.1.70",
              "prefer_older_binary": false,
              "requirements": [
                "ansicolors"
              ],
              "requires_python": [],
              "resolver_version": "pip-legacy-resolver",
              "style": "strict",
              "transitive": true,
              "use_pep517": null
            }
            """
            ).encode()
        )
        == 3
    )


class TestResolveConfigPexArgs:
    def simple_config_args(self, manylinux=None, only_binary=None, no_binary=None):
        return tuple(
            ResolveConfig(
                indexes=[],
                find_links=[],
                manylinux=manylinux,
                constraints_file=None,
                no_binary=FrozenOrderedSet(no_binary) if no_binary else FrozenOrderedSet(),
                only_binary=FrozenOrderedSet(only_binary) if only_binary else FrozenOrderedSet(),
                excludes=FrozenOrderedSet(),
                overrides=FrozenOrderedSet(),
                sources=FrozenOrderedSet(),
                path_mappings=[],
                lock_style="universal",
                complete_platforms=(),
                uploaded_prior_to=None,
            ).pex_args()
        )

    def test_minimal(self):
        args = self.simple_config_args()
        assert len(args) == 2

    def test_manylinux(self):
        assert "--no-manylinux" in self.simple_config_args()

        many = "manylinux2014_ppc64le"
        args = self.simple_config_args(manylinux=many)
        assert len(args) == 3
        assert ("--manylinux", many) in itertools.pairwise(args)

    def test_only_binary(self):
        assert "--only-binary=foo" in self.simple_config_args(only_binary=["foo"])
        assert ("--only-binary=foo", "--only-binary=bar") in itertools.pairwise(
            self.simple_config_args(only_binary=["foo", "bar"])
        )

    def test_only_binary_all(self):
        args = self.simple_config_args(only_binary=[":all:"])
        assert "--wheel" in args
        assert "--no-build" in args
        assert "--only-binary" not in " ".join(args)

        args = self.simple_config_args(only_binary=["foo", ":all:"])
        assert "--wheel" in args
        assert "--no-build" in args
        assert "--only-binary" not in " ".join(args)

    def test_only_binary_none(self):
        assert "--wheel" not in self.simple_config_args(only_binary=[":none:"])
        assert "--only-binary" not in " ".join(self.simple_config_args(only_binary=[":none:"]))
        assert "--build" in self.simple_config_args(only_binary=[":none:"])

    def test_no_binary(self):
        assert "--only-build=foo" in self.simple_config_args(no_binary=["foo"])
        assert ("--only-build=foo", "--only-build=bar") in itertools.pairwise(
            self.simple_config_args(no_binary=["foo", "bar"])
        )

    def test_no_binary_all(self):
        args = self.simple_config_args(no_binary=[":all:"])
        assert "--build" in args
        assert "--no-wheel" in args
        assert "--no-binary" not in args

    def test_no_binary_none(self):
        assert "--wheel" in self.simple_config_args(no_binary=[":none:"])
        assert "--only-build" not in " ".join(self.simple_config_args(no_binary=[":none:"]))

        assert "--wheel" in self.simple_config_args(no_binary=["foo", ":none:"])
        assert "--only-build" not in " ".join(self.simple_config_args(no_binary=["foo", ":none:"]))

    def test_uploaded_prior_to(self):
        args = self.simple_config_args()
        assert "--uploaded-prior-to" not in " ".join(args)

        args = tuple(
            ResolveConfig(
                indexes=[],
                find_links=[],
                manylinux=None,
                constraints_file=None,
                no_binary=FrozenOrderedSet(),
                only_binary=FrozenOrderedSet(),
                excludes=FrozenOrderedSet(),
                overrides=FrozenOrderedSet(),
                sources=FrozenOrderedSet(),
                path_mappings=[],
                lock_style="universal",
                complete_platforms=(),
                uploaded_prior_to="2023-09-20",
            ).pex_args()
        )
        assert "--uploaded-prior-to=2023-09-20" in args


def _uv_config(
    indexes=None,
    find_links=None,
    extra_find_links=(),
    sources=None,
    only_binary=None,
    no_binary=None,
    uploaded_prior_to=None,
):
    cfg = ResolveConfig(
        indexes=indexes if indexes is not None else ["https://pypi.org/simple"],
        find_links=find_links or [],
        manylinux=None,
        constraints_file=None,
        no_binary=FrozenOrderedSet(no_binary or []),
        only_binary=FrozenOrderedSet(only_binary or []),
        excludes=FrozenOrderedSet(),
        overrides=FrozenOrderedSet(),
        sources=FrozenOrderedSet(sources or []),
        path_mappings=[],
        lock_style="universal",
        complete_platforms=(),
        uploaded_prior_to=uploaded_prior_to,
    )
    return tomllib.loads(cfg.uv_config(extra_find_links=extra_find_links))


def test_uv_config_indexes():
    parsed = _uv_config(indexes=[])
    assert parsed.get("no-index") is True
    assert "index" not in parsed

    parsed = _uv_config(indexes=["https://example.com/simple"])
    assert len(parsed["index"]) == 1
    assert parsed["index"][0]["url"] == "https://example.com/simple"
    assert parsed["index"][0]["default"] is True

    parsed = _uv_config(
        indexes=[
            "https://primary.example.com/simple",
            "fallback=https://secondary.example.com/simple",
        ]
    )
    indexes = parsed["index"]
    assert len(indexes) == 2
    assert indexes[0]["url"] == "https://primary.example.com/simple"
    assert "name" not in indexes[0]
    assert "default" not in indexes[0]
    assert indexes[1]["url"] == "https://secondary.example.com/simple"
    assert indexes[1].get("name") == "fallback"
    assert indexes[1]["default"] is True


def test_uv_config_find_links():
    parsed = _uv_config(find_links=["https://example.com/wheels"])
    assert parsed["find-links"] == ["https://example.com/wheels"]

    parsed = _uv_config(
        find_links=["https://a.example.com/wheels"],
        extra_find_links=("https://b.example.com/wheels",),
    )
    assert parsed["find-links"] == [
        "https://a.example.com/wheels",
        "https://b.example.com/wheels",
    ]


def test_uv_config_sources():
    parsed = _uv_config(sources=[])
    assert "sources" not in parsed

    parsed = _uv_config(sources=["myindex=requests>=2.0"])
    assert parsed["sources"] == {"requests": {"index": "myindex"}}

    parsed = _uv_config(sources=['myindex=requests>=2.0; python_version > "3.8"'])
    assert parsed["sources"]["requests"]["index"] == "myindex"
    assert "python_version" in parsed["sources"]["requests"]["marker"]

    parsed = _uv_config(sources=["indexa=requests>=2.0", "indexb=boto3>=1.0"])
    assert parsed["sources"]["requests"] == {"index": "indexa"}
    assert parsed["sources"]["boto3"] == {"index": "indexb"}


def test_uv_config_no_binary():
    parsed = _uv_config(no_binary=["foo", "bar"])
    assert parsed["no-binary-package"] == ["foo", "bar"]
    assert "no-binary" not in parsed

    parsed = _uv_config(no_binary=[":all:"])
    assert parsed.get("no-binary") is True
    assert "no-binary-package" not in parsed

    # :all: wins even when combined with package names
    parsed = _uv_config(no_binary=["foo", ":all:"])
    assert parsed.get("no-binary") is True
    assert "no-binary-package" not in parsed

    # :none: means "no restriction" — no key emitted
    parsed = _uv_config(no_binary=[":none:"])
    assert "no-binary" not in parsed
    assert "no-binary-package" not in parsed


def test_uv_config_only_binary():
    parsed = _uv_config(only_binary=["foo", "bar"])
    assert parsed["no-build-package"] == ["foo", "bar"]
    assert "no-build" not in parsed

    parsed = _uv_config(only_binary=[":all:"])
    assert parsed.get("no-build") is True
    assert "no-build-package" not in parsed

    parsed = _uv_config(only_binary=["foo", ":all:"])
    assert parsed.get("no-build") is True
    assert "no-build-package" not in parsed

    parsed = _uv_config(only_binary=[":none:"])
    assert "no-build" not in parsed
    assert "no-build-package" not in parsed


def test_uv_config_exclude_newer():
    parsed = _uv_config(uploaded_prior_to="2023-09-20")
    assert parsed["exclude-newer"] == "2023-09-20"

    parsed = _uv_config()
    assert "exclude-newer" not in parsed
