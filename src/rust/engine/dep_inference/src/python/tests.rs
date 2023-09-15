// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::python::{get_dependencies, ImportCollector};
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;

fn assert_collected(
  code: &str,
  import_map: HashMap<&str, (u64, bool)>,
  string_candidates: HashMap<&str, u64>,
) {
  let mut collector = ImportCollector::new(code);
  collector.collect();
  assert_eq!(
    HashMap::from_iter(import_map.iter().map(|(k, v)| (k.to_string(), v.clone()))),
    collector.import_map
  );
  assert_eq!(
    HashMap::from_iter(
      string_candidates
        .iter()
        .map(|(k, v)| (k.to_string(), v.clone()))
    ),
    collector.string_candidates
  );
}

fn assert_imports(code: &str, imports: &[&str]) {
  let mut collector = ImportCollector::new(code);
  collector.collect();
  assert_eq!(
    HashSet::from_iter(imports.iter().map(|s| s.to_string())),
    collector.import_map.keys().cloned().collect::<HashSet<_>>()
  );
}

#[test]
fn simple_imports() {
  assert_imports("import a", &["a"]);
  assert_imports("import a.b", &["a.b"]);
  assert_imports("import a as x", &["a"]);
  assert_imports("from a import b", &["a.b"]);
  assert_imports("from a import *", &["a"]);
  assert_imports("from a.b import c", &["a.b.c"]);
  assert_imports("from a.b import c.d", &["a.b.c.d"]);
  assert_imports("from a.b import c, d, e", &["a.b.c", "a.b.d", "a.b.e"]);
  assert_imports(
    r"
from a.b import (
    c,
    d,
    e,
)
  ",
    &["a.b.c", "a.b.d", "a.b.e"],
  );
  assert_imports(
    r"
from a.b import (
    c,

    d,

    e,
)
  ",
    &["a.b.c", "a.b.d", "a.b.e"],
  );
  assert_imports(
    r"
from a.b import (
    c as x,
    d as y,
    e as z,
)
  ",
    &["a.b.c", "a.b.d", "a.b.e"],
  );

  assert_imports("from . import b", &[".b"]);
  assert_imports("from .a import b", &[".a.b"]);
  assert_imports("from .. import b", &["..b"]);
  assert_imports("from ..a import b", &["..a.b"]);
  assert_imports("from ..a import b.c", &["..a.b.c"]);
  assert_imports("from ... import b.c", &["...b.c"]);
  assert_imports("from ...a import b.c", &["...a.b.c"]);
  assert_imports("from ....a import b.c", &["....a.b.c"]);
  assert_imports("from ....a import b, c", &["....a.b", "....a.c"]);
  assert_imports("from ....a import b as d, c", &["....a.b", "....a.c"]);

  assert_imports("from .a import *", &[".a"]);
  assert_imports("from . import *", &["."]);
  assert_imports("from ..a import *", &["..a"]);
  assert_imports("from .. import *", &[".."]);

  assert_imports(
    "class X: def method(): if True: while True: class Y: def f(): import a",
    &["a"],
  );
  assert_imports("try:\nexcept:import a", &["a"]);

  // NB: Doesn't collect __future__ imports
  assert_imports("from __future__ import annotations", &[]);
}

#[test]
fn pragma_ignore() {
  assert_imports("import a  # pants: no-infer-dep", &[]);
  assert_imports("import a.b  # pants: no-infer-dep", &[]);
  assert_imports("import a.b as d  # pants: no-infer-dep", &[]);
  assert_imports("from a import b  # pants: no-infer-dep", &[]);
  assert_imports("from a import *  # pants: no-infer-dep", &[]);
  assert_imports("from a import b, c  # pants: no-infer-dep", &[]);
  assert_imports("from a import b, c as d  # pants: no-infer-dep", &[]);
  assert_imports(
    r"
    from a.b import (
        c  # pants: no-infer-dep
    )",
    &[],
  );
  assert_imports(
    r"
    from a.b import (
        c as d  # pants: no-infer-dep
    )",
    &[],
  );
  assert_imports(
    r"
    from a.b import (
        a,
        c,  # pants: no-infer-dep
        d,
    )",
    &["a.b.a", "a.b.d"],
  );
  assert_imports(
    r"
    from a.b import (
        c as cc,  # pants: no-infer-dep
    )",
    &[],
  );
  assert_imports(
    r"
    from a.b import (
        c
        as dd,  # pants: no-infer-dep
    )",
    &[],
  );
  assert_imports(
    r"
    from a.b import (
        c,
        d,
        e
    )  # pants: no-infer-dep",
    &[],
  );
  assert_imports(
    r"
    from a import (b,  # pants: no-infer-dep
        c)",
    &["a.c"],
  );

  // Now let's have fun with line continuations
  assert_imports(
    r"
    from a.b import \
        c  # pants: no-infer-dep",
    &[],
  );
  assert_imports(
    r"
    from a.b \
      import \
        c  # pants: no-infer-dep",
    &[],
  );
  assert_imports(
    r"
    from a.b import (
        c
        as \
        dd,  # pants: no-infer-dep
    )",
    &[],
  );
  assert_imports(
    r"
    from a.b import \
        *  # pants: no-infer-dep",
    &[],
  );
  // Imports nested within other constructs
  assert_imports(
    r"
    if x:
        import a  # pants: no-infer-dep
    ",
    &[],
  );
  assert_imports(
    r"
    if x:
        import a  # pants: no-infer-dep
        import b
    ",
    &["b"],
  );
  assert_imports(
    r"
    class X: def method(): if True: while True: class Y: def f(): import a  # pants: no-infer-dep
    ",
    &[],
  );
  assert_imports(
    r"
    if x:
        import \
            a  # pants: no-infer-dep
    ",
    &[],
  );

  // https://github.com/pantsbuild/pants/issues/19751
  assert_imports(
    r"
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from a import ClassA  # pants: no-infer-dep

    print('Hello, world!')",
    &["typing.TYPE_CHECKING"],
  );
}

#[test]
fn dunder_import() {
  assert_imports("__import__('pkg_resources')", &["pkg_resources"]);
  assert_imports("__import__(b'pkg_resources')", &["pkg_resources"]);
  assert_imports("__import__(u'pkg_resources')", &["pkg_resources"]);
  assert_imports("__import__(f'pkg_resources')", &["pkg_resources"]);
  assert_imports("__import__('''pkg_resources''')", &["pkg_resources"]);
  assert_imports("__import__('ignored')  # pants: no-infer-dep", &[]);
  assert_imports(
    r"
    __import__(  # pants: no-infer-dep
        'ignored'
    )",
    &[],
  );
  assert_imports(
    r"
    __import__(
        'ignored'  # pants: no-infer-dep
    )",
    &[],
  );
  assert_imports(
    r"
    __import__(
        'ignored'
    )  # pants: no-infer-dep",
    &[],
  );
  assert_imports(
    r"
    __import__(
        'not_ignored' \
        # pants: no-infer-dep
    )",
    &["not_ignored"],
  );
  assert_imports(
    r"
    __import__(
        'ignored' \
    )  # pants: no-infer-dep",
    &[],
  );
}

fn assert_imports_strong_weak(code: &str, strong: &[&str], weak: &[&str]) {
  let mut collector = ImportCollector::new(code);
  collector.collect();
  let (actual_weak, actual_strong): (Vec<_>, Vec<_>) =
    collector.import_map.iter().partition(|(_, v)| v.1);
  let expected_weak = HashSet::from_iter(weak.iter().map(|s| s.to_string()));
  let found_weak = actual_weak
    .iter()
    .map(|(k, _)| k.to_string())
    .collect::<HashSet<_>>();
  assert_eq!(
    expected_weak, found_weak,
    "weak imports did not match, expected={:?} found={:?}",
    expected_weak, found_weak
  );
  let expected_strong = HashSet::from_iter(strong.iter().map(|s| s.to_string()));
  let found_strong = actual_strong
    .iter()
    .map(|(k, _)| k.to_string())
    .collect::<HashSet<_>>();
  assert_eq!(
    expected_strong, found_strong,
    "strong imports did not match, expected={:?} found={:?}",
    expected_strong, found_strong
  );
}

#[test]
fn tryexcept_weak_imports() {
  assert_imports_strong_weak(
    r"
    try: import strong
    except AssertionError: pass",
    &["strong"],
    &[],
  );
  assert_imports_strong_weak(
    r"
    try: import weak
    except ImportError: pass",
    &[],
    &["weak"],
  );
  assert_imports_strong_weak(
    r"
    try: import weak
    except (AssertionError, ImportError): pass",
    &[],
    &["weak"],
  );
  assert_imports_strong_weak(
    r"
    try: import weak
    except (AssertionError, ImportError): pass",
    &[],
    &["weak"],
  );
  assert_imports_strong_weak(
    r"
    try: import weak
    except [AssertionError, ImportError]: pass",
    &[],
    &["weak"],
  );
  assert_imports_strong_weak(
    r"
    try: import weak
    except {AssertionError, ImportError}: pass",
    &[],
    &["weak"],
  );
  assert_imports_strong_weak(
    r"
    try: import weak
    except AssertionError: pass
    except ImportError: pass",
    &[],
    &["weak"],
  );
  assert_imports_strong_weak(
    r"
    try: import weak
    except AssertionError: import strong1
    except ImportError: import strong2
    else: import strong3
    finally: import strong4",
    &["strong1", "strong2", "strong3", "strong4"],
    &["weak"],
  );
  assert_imports_strong_weak(
    r"
    try: pass
    except AssertionError:
        try: import weak
        except ImportError: import strong",
    &["strong"],
    &["weak"],
  );
  assert_imports_strong_weak(
    r"
    try: import strong
    # This would be too complicated to try and handle
    except (lambda: ImportError)(): pass",
    &["strong"],
    &[],
  );
  assert_imports_strong_weak(
    r"
    ImpError = ImportError
    try: import strong
    # This would be too complicated to try and handle
    except ImpError: pass",
    &["strong"],
    &[],
  );
  assert_imports_strong_weak(
    r"
    try: import ignored_weak  # pants: no-infer-dep
    except ImportError: import strong",
    &["strong"],
    &[],
  );
  // NB: The `pass` forces the comment to be parsed as inside the except clause.
  //  Otherwise it is parsed after the entire try statement.
  assert_imports_strong_weak(
    r"
    try: import weak
    except ImportError: import ignored_strong  # pants: no-infer-dep
    pass",
    &[],
    &["weak"],
  );
  assert_imports_strong_weak(
    r"
    try: import ignored_weak  # pants: no-infer-dep
    except ImportError: import ignored_strong  # pants: no-infer-dep
    pass",
    &[],
    &[],
  );

  assert_imports_strong_weak(
    r"
    try:
      # A comment
      import one.two.three
      from one import four
    except ImportError:
      pass",
    &[],
    &["one.two.three", "one.four"],
  );

  // Some conflict in strength
  assert_imports_strong_weak(
    r"
    import one.two.three
    try: import one.two.three
    except ImportError: pass",
    &["one.two.three"],
    &[],
  );
  assert_imports_strong_weak(
    r"
    try: import one.two.three
    except ImportError: pass
    import one.two.three",
    &["one.two.three"],
    &[],
  );
  // Ensure we preserve the stack of weakens with try-except
  assert_imports_strong_weak(
    r"
    try:
        with suppress(ImportError):
            import weak0
        import weak1
    except ImportError:
        with suppress(ImportError):
            import weak2
        import strong0
    import strong1
    ",
    &["strong0", "strong1"],
    &["weak0", "weak1", "weak2"],
  );
}
#[test]
fn tryexcept_weak_imports_dunder() {
  assert_imports_strong_weak(
    r"
    __import__('strong')
    try:
      __import__('weak')
    except ImportError:
      pass
    ",
    &["strong"],
    &["weak"],
  )
}

#[test]
fn contextlib_suppress_weak_imports() {
  // standard contextlib.suppress
  assert_imports_strong_weak(
    r"
    with contextlib.suppress(ImportError):
        import weak0
    ",
    &[],
    &["weak0"],
  );
  // ensure we reset the weakened status
  assert_imports_strong_weak(
    r"
    with contextlib.suppress(ImportError):
        import weak0

    import strong0
    ",
    &["strong0"],
    &["weak0"],
  );
  // Allow other error types to be suppressed
  assert_imports_strong_weak(
    r"
    with suppress(NameError, ImportError):
        import weak0
    ",
    &[],
    &["weak0"],
  );
  // We should respect the intention of any function that is obviously suppressing ImportErrors
  assert_imports_strong_weak(
    r"
    with suppress(ImportError):
        import weak0
    ",
    &[],
    &["weak0"],
  );
  // We should not weaken because of other suppressions
  assert_imports_strong_weak(
    r"
    with contextlib.suppress(NameError):
        import strong0
      ",
    &["strong0"],
    &[],
  );
  // Ensure we preserve the stack of weakens
  assert_imports_strong_weak(
    r"
    with suppress(ImportError):
        import weak0
        with suppress(ImportError):
            import weak1
        import weak2
    ",
    &[],
    &["weak0", "weak1", "weak2"],
  );
  // Ensure we preserve the stack of weakens with try-except
  assert_imports_strong_weak(
    r"
    with suppress(ImportError):
        try:
            import weak0
        except ImportError:
            import weak1
        import weak2
    ",
    &[],
    &["weak0", "weak1", "weak2"],
  );
  // Ensure we aren't affected by weirdness in tree-sitter
  // where in the viewer the second import wasn't assigned the correct parent
  assert_imports_strong_weak(
    r"
    with suppress(ImportError):
        import weak0
        import weak1
    ",
    &[],
    &["weak0", "weak1"],
  );
  // Ensure that we still traverse withitems
  let withitems_open = r"
    with (
        open('/dev/null') as f0,
        open('data/subdir1/a.json') as f1,
    ):
        pass
    ";
  assert_imports_strong_weak(withitems_open, &[], &[]);
  assert_strings(withitems_open, &["/dev/null", "data/subdir1/a.json"]);
  // Ensure suppress bound to variable
  assert_imports_strong_weak(
    r"
    with suppress(ImportError) as e:
        import weak0
    ",
    &[],
    &["weak0"],
  );
  // Ensure multiple items in `with`
  assert_imports_strong_weak(
    r"
    with open('file') as f, suppress(ImportError):
        import weak0
    ",
    &[],
    &["weak0"],
  );
  // Ensure multiple with_items
  assert_imports_strong_weak(
    r"
    with suppress(ImportError), open('file'):
        import weak0
    ",
    &[],
    &["weak0"],
    // &["weak0"],
  );
  // Ensure multiple with_items in parens (with trailing comma)
  assert_imports_strong_weak(
    r"
    with (suppress(ImportError), open('file'),):
        import weak0
    ",
    &[],
    &["weak0"],
  );
  // pathological: suppress without a child
  assert_imports_strong_weak(
    r"
    with suppress():
        import strong0
    ",
    &["strong0"],
    &[],
  );
  // pathological: nothing in `with` clause
  assert_imports_strong_weak(
    r"
    with:
      import strong0
    ",
    &["strong0"],
    &[],
  );
}

#[test]
fn contextlib_suppress_weak_imports_dunder() {
  assert_imports_strong_weak(
    r"
    __import__('strong')
    with contextlib.suppress(ImportError):
      __import__('weak')
    ",
    &["strong"],
    &["weak"],
  )
}

fn assert_strings(code: &str, strings: &[&str]) {
  let mut collector = ImportCollector::new(code);
  collector.collect();
  assert_eq!(
    HashSet::from_iter(strings.iter().map(|s| s.to_string())),
    collector
      .string_candidates
      .keys()
      .cloned()
      .collect::<HashSet<_>>()
  );
}

#[test]
fn string_candidates() {
  assert_strings("'a'", &["a"]);
  assert_strings("'''a'''", &["a"]);
  assert_strings("'a.b'", &["a.b"]);
  assert_strings("'a.b.c_狗'", &["a.b.c_狗"]);
  assert_strings("'..a.b.c.d'", &["..a.b.c.d"]);

  // Not candidates
  assert_strings("'I\\\\have\\\\backslashes'", &[]);
  assert_strings("'I have whitespace'", &[]);
  assert_strings("'\ttabby'", &[]);
  assert_strings("'\\ttabby'", &[]);
  assert_strings("'\\nnewline'", &[]);
  assert_strings("'''\na'''", &[]);
  assert_strings("'''a\n'''", &[]);

  // Technically the value of the string doesn't contain whitespace, but the parser isn't that
  // sophisticated yet.
  assert_strings("'''\\\na'''", &[]);
}

#[test]
fn python2() {
  assert_collected(
    r"# -*- coding: utf-8 -*-
        print 'Python 2 lives on.'

        import demo
        from project.demo import Demo

      __import__(u'pkg_resources')
      __import__(b'treat.as.a.regular.import.not.a.string.import')
      __import__(u'{}'.format('interpolation'))

        importlib.import_module(b'dep.from.bytes')
        importlib.import_module(u'dep.from.str')
        importlib.import_module(u'dep.from.str_狗')

        b'\\xa0 a non-utf8 string, make sure we ignore it'

        try: import weak1
        except ImportError: import strong1
        else: import strong2
        finally: import strong3",
    HashMap::from([
      ("demo", (4, false)),
      ("project.demo.Demo", (5, false)),
      ("pkg_resources", (7, false)),
      ("treat.as.a.regular.import.not.a.string.import", (8, false)),
      ("weak1", (17, true)),
      ("strong1", (18, false)),
      ("strong2", (19, false)),
      ("strong3", (20, false)),
    ]),
    HashMap::from([
      ("dep.from.bytes", 11),
      ("dep.from.str", 12),
      ("dep.from.str_狗", 13),
    ]),
  );
}

#[test]
fn still_parses_from_syntax_error() {
  assert_imports("import a; x=", &["a"]);
}

fn assert_relative_imports(filename: &str, code: &str, resolved_imports: &[&str]) {
  let result = get_dependencies(code, PathBuf::from(filename)).unwrap();
  assert_eq!(
    HashSet::from_iter(resolved_imports.iter().map(|s| s.to_string())),
    result.imports.keys().cloned().collect::<HashSet<_>>()
  );
}

#[test]
fn relative_imports_resolution() {
  let filename = "foo/bar/baz.py";
  assert_relative_imports(filename, "from . import b", &["foo.bar.b"]);
  assert_relative_imports(filename, "from . import *", &["foo.bar"]);
  assert_relative_imports(filename, "from .a import b", &["foo.bar.a.b"]);
  assert_relative_imports(filename, "from .a import *", &["foo.bar.a"]);
  assert_relative_imports(filename, "from .. import b", &["foo.b"]);
  assert_relative_imports(filename, "from .. import *", &["foo"]);
  assert_relative_imports(filename, "from ..a import b", &["foo.a.b"]);
  assert_relative_imports(filename, "from .. import b.c", &["foo.b.c"]);
  assert_relative_imports(filename, "from ..a import b.c", &["foo.a.b.c"]);

  let filename = "bingo/bango/bongo/himom.py";
  assert_relative_imports(filename, "from . import b", &["bingo.bango.bongo.b"]);
  assert_relative_imports(filename, "from .a import b", &["bingo.bango.bongo.a.b"]);
  assert_relative_imports(filename, "from ..a import b", &["bingo.bango.a.b"]);
  assert_relative_imports(filename, "from ..a import b.c", &["bingo.bango.a.b.c"]);
  assert_relative_imports(filename, "from ... import b.c", &["bingo.b.c"]);
  assert_relative_imports(filename, "from ...a import b.c", &["bingo.a.b.c"]);

  // Left unchanged, since we blew through the top, let Pants error using this string as a message
  assert_relative_imports(filename, "from .... import b.c", &["....b.c"]);
  assert_relative_imports(filename, "from ....a import b.c", &["....a.b.c"]);
  assert_relative_imports(filename, "from ....a import b, c", &["....a.b", "....a.c"]);
  assert_relative_imports(
    filename,
    "from ....a import b as d, c",
    &["....a.b", "....a.c"],
  );
}

#[test]
fn syntax_errors_and_other_fun() {
  // These tests aren't specifically testing what we parse, so much as we don't "crash and burn".

  assert_imports("imprt a", &[]);
  assert_imports("form a import b", &["b"]);
  assert_imports("import .b", &["."]);
  assert_imports("import a....b", &["a....b"]);
  assert_imports("import a.", &[]);
  assert_imports("import *", &[]);
  assert_imports("from a import", &[]);
  assert_imports("from a import;", &["a."]);
  assert_imports("from a import ()", &["a."]);
  assert_imports("from a imp x", &[]);
  assert_imports("from from import a as .as", &[]);
  assert_imports("from a import ......g", &["a.g"]);
  assert_imports("from a. import b", &[]);
  assert_imports("from a as c import b as d", &["a.b"]);
  assert_imports("from a import *, b", &["a"]);
  assert_imports("from a import b, *", &["a.b"]);
  assert_imports("from a import (*)", &[]);
  assert_imports("from * import b", &["b"]);
  assert_imports("try:...\nexcept:import a", &["a"]);
  assert_imports("try:...\nexcept 1:import a", &["a"]);
  assert_imports("try:...\nexcept x=1:import a", &["a"]);
  assert_imports("try:...\nexcept (x=1):import a", &["a"]);
  assert_imports("foo()", &[]);
}
