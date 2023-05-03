use crate::python::ImportCollector;
use std::collections::{HashMap, HashSet};

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
  assert_imports("from ..a import b", &["..a.b"]);
  assert_imports("from ..a import b.c", &["..a.b.c"]);
  assert_imports("from ...a import b.c", &["...a.b.c"]);
  assert_imports("from ....a import b.c", &["....a.b.c"]);
  assert_imports("from ....a import b, c", &["....a.b", "....a.c"]);
  assert_imports("from ....a import b as d, c", &["....a.b", "....a.c"]);

  // NB: Doesn't collect __future__ imports
  assert_imports("from __future__ import annotations", &[]);
}

#[test]
fn pragma_ignore() {
  assert_imports("import a  # pants: no-infer-dep", &[]);
  assert_imports("import a.b  # pants: no-infer-dep", &[]);
  assert_imports("import a.b as d  # pants: no-infer-dep", &[]);
  assert_imports("from a import b  # pants: no-infer-dep", &[]);
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
  assert_eq!(
    HashSet::from_iter(weak.iter().map(|s| s.to_string())),
    actual_weak
      .iter()
      .map(|(k, _)| k.to_string())
      .collect::<HashSet<_>>()
  );
  assert_eq!(
    HashSet::from_iter(strong.iter().map(|s| s.to_string())),
    actual_strong
      .iter()
      .map(|(k, _)| k.to_string())
      .collect::<HashSet<_>>()
  );
}

#[test]
fn weak_imports() {
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
