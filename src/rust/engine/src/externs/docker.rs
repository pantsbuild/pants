// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::borrow::Cow;

use fnv::FnvHashSet;
use glob::{MatchOptions, Pattern};
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedStr;
use pyo3::types::PyList;
use smallvec::{SmallVec, smallvec};
use strsim::normalized_levenshtein;

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(suggest_renames, m)?)
}

/// Match `tentative_paths` (COPY sources from a Dockerfile) against the actual build context,
/// pairing each unknown path with its best rename candidate, and listing unused context files.
#[pyfunction]
fn suggest_renames<'py>(
    py: Python<'py>,
    tentative_paths: Vec<PyBackedStr>,
    actual_files: Vec<PyBackedStr>,
    actual_dirs: Vec<PyBackedStr>,
) -> PyResult<Bound<'py, PyList>> {
    let pairs = py.detach(|| suggest_renames_impl(&tentative_paths, &actual_files, &actual_dirs));
    let to_py_str = |slot: Option<&PyBackedStr>| match slot {
        Some(s) => s
            .into_pyobject(py)
            .expect("PyBackedStr to str conversion is infallible"),
        None => intern!(py, "").clone(),
    };
    PyList::new(py, pairs.iter().map(|&(a, b)| (to_py_str(a), to_py_str(b))))
}

fn dirname(path: &str) -> &str {
    // Deliberately not using `std::path::Path` because docker COPY paths are always
    // forward-slash-separated.
    path.rsplit_once('/').map_or("", |(dir, _)| dir)
}

fn dir_is_referenced(referenced_dirs: &FnvHashSet<&str>, mut path: &str) -> bool {
    while !path.is_empty() {
        if referenced_dirs.contains(path) {
            return true;
        }
        path = dirname(path);
    }
    false
}

fn file_is_referenced(
    referenced_files: &FnvHashSet<&str>,
    referenced_dirs: &FnvHashSet<&str>,
    path: &str,
) -> bool {
    referenced_files.contains(path) || dir_is_referenced(referenced_dirs, dirname(path))
}

fn ancestor_dirs<'a>(files: impl IntoIterator<Item = &'a str>) -> FnvHashSet<&'a str> {
    let mut dirs = FnvHashSet::default();
    for file in files {
        let mut dir = dirname(file);
        while !dir.is_empty() && dirs.insert(dir) {
            dir = dirname(dir);
        }
    }
    dirs
}

fn is_glob(path: &str) -> bool {
    path.contains('*') || path.contains('?') || (path.contains('[') && path.contains(']'))
}

struct Renamer<'a, S: AsRef<str>> {
    actual_files: &'a [S],
    actual_dirs: &'a [S],
    actual_dirs_set: FnvHashSet<&'a str>,
    referenced_dirs: FnvHashSet<&'a str>,
    referenced_files: FnvHashSet<&'a str>,
    candidates: Option<(Vec<&'a S>, FnvHashSet<&'a str>)>,
}

impl<'a, S: AsRef<str>> Renamer<'a, S> {
    fn new(actual_files: &'a [S], actual_dirs: &'a [S]) -> Self {
        let pool: Vec<&S> = actual_files.iter().chain(actual_dirs).collect();
        let set = pool.iter().copied().map(AsRef::as_ref).collect();
        Renamer {
            actual_files,
            actual_dirs,
            actual_dirs_set: actual_dirs.iter().map(AsRef::as_ref).collect(),
            referenced_dirs: FnvHashSet::default(),
            referenced_files: FnvHashSet::default(),
            candidates: Some((pool, set)),
        }
    }

    fn reference(&mut self, path: &'a str) {
        if self.actual_dirs_set.contains(path) {
            self.referenced_dirs.insert(path);
        } else {
            self.referenced_files.insert(path);
        }
        self.candidates = None;
    }

    fn unreferenced_files(&self) -> impl Iterator<Item = &'a S> + '_ {
        self.actual_files.iter().filter(|s| {
            !file_is_referenced(&self.referenced_files, &self.referenced_dirs, s.as_ref())
        })
    }

    fn candidates(&mut self) -> &(Vec<&'a S>, FnvHashSet<&'a str>) {
        if self.candidates.is_none() {
            let mut pool: Vec<&S> = self.unreferenced_files().collect();
            let dirs_with_files = ancestor_dirs(pool.iter().copied().map(AsRef::as_ref));
            pool.extend(self.actual_dirs.iter().filter(|s| {
                let dir = s.as_ref();
                dirs_with_files.contains(dir) && !dir_is_referenced(&self.referenced_dirs, dir)
            }));
            let set = pool.iter().copied().map(AsRef::as_ref).collect();
            self.candidates = Some((pool, set));
        }
        self.candidates.as_ref().unwrap()
    }

    fn get_matches(&mut self, path: &'a str) -> SmallVec<[&'a str; 2]> {
        let glob = is_glob(path);
        let (pool, set) = self.candidates();
        if !glob {
            return if set.contains(path) {
                smallvec![path]
            } else {
                SmallVec::new()
            };
        }
        let pattern = PathPattern::new(path);
        pool.iter()
            .copied()
            .filter_map(|s| {
                let candidate = s.as_ref();
                pattern.matches(candidate).then_some(candidate)
            })
            .collect()
    }

    fn reference_matches(&mut self, tentative_paths: &'a [S]) -> Vec<&'a S> {
        let mut unmatched: Vec<&S> = Vec::new();
        for path in tentative_paths {
            let matches = self.get_matches(path.as_ref());
            if matches.is_empty() {
                unmatched.push(path);
            }
            for matched in matches {
                self.reference(matched);
            }
        }
        unmatched.sort_unstable_by(|a, b| a.as_ref().cmp(b.as_ref()));
        unmatched.dedup_by(|a, b| a.as_ref() == b.as_ref());
        unmatched
    }

    fn rename_suggestions(&mut self, unmatched: Vec<&'a S>) -> Vec<(Option<&'a S>, Option<&'a S>)> {
        let mut suggestions = Vec::with_capacity(unmatched.len());
        for path in unmatched {
            let suggestion = {
                let (pool, _) = self.candidates();
                get_close_match(path.as_ref(), pool.iter().copied(), RENAME_CUTOFF)
            };
            if let Some(suggestion) = suggestion {
                self.reference(suggestion.as_ref());
            }
            suggestions.push((Some(path), suggestion));
        }
        suggestions
    }

    fn unreferenced_files_sorted(&self) -> Vec<&'a S> {
        let mut files: Vec<&S> = self.unreferenced_files().collect();
        files.sort_unstable_by(|a, b| a.as_ref().cmp(b.as_ref()));
        files
    }
}

fn suggest_renames_impl<'a, S: AsRef<str>>(
    tentative_paths: &'a [S],
    actual_files: &'a [S],
    actual_dirs: &'a [S],
) -> Vec<(Option<&'a S>, Option<&'a S>)> {
    let mut renamer = Renamer::new(actual_files, actual_dirs);
    let unmatched = renamer.reference_matches(tentative_paths);
    let mut result = renamer.rename_suggestions(unmatched);
    result.extend(
        renamer
            .unreferenced_files_sorted()
            .into_iter()
            .map(|f| (None, Some(f))),
    );
    result
}

/// Minimum normalized-Levenshtein similarity for offering a rename suggestion.
const RENAME_CUTOFF: f64 = 0.1;

/// Highest-scoring candidate at or above `cutoff` by normalized Levenshtein ratio; ties prefer the
/// lexicographically greatest.
fn get_close_match<'a, S: AsRef<str>>(
    word: &str,
    candidates: impl IntoIterator<Item = &'a S>,
    cutoff: f64,
) -> Option<&'a S> {
    let word_len = word.chars().count();
    candidates
        .into_iter()
        .filter(|c| max_similarity(c.as_ref().chars().count(), word_len) >= cutoff)
        .map(|c| (normalized_levenshtein(c.as_ref(), word), c))
        .filter(|(ratio, _)| *ratio >= cutoff)
        .max_by(|(r1, c1), (r2, c2)| r1.total_cmp(r2).then_with(|| c1.as_ref().cmp(c2.as_ref())))
        .map(|(_, c)| c)
}

/// Fast path upper bound on the normalized-Levenshtein ratio reachable given only the two lengths.
fn max_similarity(a_len: usize, b_len: usize) -> f64 {
    let max = a_len.max(b_len);
    if max == 0 {
        1.0
    } else {
        1.0 - a_len.abs_diff(b_len) as f64 / max as f64
    }
}

/// Docker `COPY` glob matching (Go's `path/filepath.Match`): `*`/`?` stay within a path component.
/// Runs of `*` are collapsed so `glob`'s `**` never fires; an unparseable pattern is literal.
enum PathPattern<'a> {
    Glob(Pattern),
    Literal(&'a str),
}

const MATCH_OPTIONS: MatchOptions = MatchOptions {
    case_sensitive: true,
    require_literal_separator: true,
    require_literal_leading_dot: false,
};

impl<'a> PathPattern<'a> {
    fn new(pattern: &'a str) -> Self {
        let collapsed: Cow<str> = if pattern.contains("**") {
            Cow::Owned(collapse_star_runs(pattern))
        } else {
            Cow::Borrowed(pattern)
        };
        match Pattern::new(&collapsed) {
            Ok(glob) => PathPattern::Glob(glob),
            Err(_) => PathPattern::Literal(pattern),
        }
    }

    fn matches(&self, path: &str) -> bool {
        match self {
            PathPattern::Glob(pattern) => pattern.matches_with(path, MATCH_OPTIONS),
            PathPattern::Literal(literal) => *literal == path,
        }
    }
}

fn collapse_star_runs(pattern: &str) -> String {
    let mut out = String::with_capacity(pattern.len());
    for c in pattern.chars() {
        if c != '*' || !out.ends_with('*') {
            out.push(c);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn renames<'a>(
        tentative: &'a [&'a str],
        files: &'a [&'a str],
        dirs: &'a [&'a str],
    ) -> Vec<(&'a str, &'a str)> {
        suggest_renames_impl(tentative, files, dirs)
            .into_iter()
            .map(|(a, b)| (a.map_or("", |s| *s), b.map_or("", |s| *s)))
            .collect()
    }

    fn pairs<'a>(expected: &[(&'a str, &'a str)]) -> Vec<(&'a str, &'a str)> {
        expected.to_vec()
    }

    // The cases below mirror `test_suggest_renames` in
    // `src/python/pants/backend/docker/utils_test.py`.

    #[test]
    fn suggest_rename_simple() {
        assert_eq!(
            renames(&["src/project/cmd.pex"], &["src.project/cmd.pex"], &[]),
            pairs(&[("src/project/cmd.pex", "src.project/cmd.pex")]),
        );
    }

    #[test]
    fn suggest_rename_false_positive() {
        assert_eq!(
            renames(
                &["src/project/cmd.pex"],
                &["src/unrelated/file.py"],
                &["src/unrelated"],
            ),
            pairs(&[("src/project/cmd.pex", "src/unrelated/file.py")]),
        );
    }

    #[test]
    fn copying_folder_includes_tree_below() {
        assert_eq!(
            renames(
                &["files"],
                &[
                    "src/docker/files/a.txt",
                    "src/docker/files/b.txt",
                    "src/docker/files/sub/c.txt",
                    "src/docker/config.ini",
                ],
                &["src", "src/docker", "src/docker/files"],
            ),
            pairs(&[("files", "src/docker/files"), ("", "src/docker/config.ini")]),
        );
    }

    #[test]
    fn no_rename_to_already_referenced_file_regardless_of_order() {
        for tentative in [
            ["src.proj/bin_a.pex", "src.proj/binb.pex"],
            ["src.proj/binb.pex", "src.proj/bin_a.pex"],
        ] {
            assert_eq!(
                renames(&tentative, &["src.proj/bin_a.pex"], &["src.proj"]),
                pairs(&[("src.proj/binb.pex", "")]),
            );
        }
    }

    #[test]
    fn glob_pattern_captures_matching_files_only() {
        assert_eq!(
            renames(
                &["src.proj/*.pex", "src.proj/config.ini"],
                &[
                    "src.proj/bin_a.pex",
                    "src.proj/bin_b.pex",
                    "src.proj/other.txt",
                    "src.proj/nested/file.txt",
                    "src/proj/config.ini",
                ],
                &["src.proj", "src/proj", "src.proj/nested"],
            ),
            pairs(&[
                ("src.proj/config.ini", "src/proj/config.ini"),
                ("", "src.proj/nested/file.txt"),
                ("", "src.proj/other.txt"),
            ]),
        );
    }

    #[test]
    fn no_rename_to_empty_directory() {
        assert_eq!(
            renames(
                &["src/project/file", "sources"],
                &["src/project/file"],
                &["src", "src/project"],
            ),
            pairs(&[("sources", "")]),
        );
    }

    #[test]
    fn skip_dockerfile() {
        assert_eq!(
            renames(
                &[
                    "testprojects/src/python/docker/Dockerfile.test-example-synth",
                    "testprojects.src.python.hello.main/mains.pez",
                    "blarg",
                    "baz",
                ],
                &[
                    "testprojects/src/python/docker/Dockerfile.test-example-synth",
                    "testprojects.src.python.hello.main/main.pex",
                ],
                &[
                    "testprojects",
                    "testprojects/src",
                    "testprojects/src/python",
                    "testprojects/src/python/docker",
                    "testprojects.src.python.hello.main",
                ],
            ),
            pairs(&[
                ("baz", ""),
                ("blarg", ""),
                (
                    "testprojects.src.python.hello.main/mains.pez",
                    "testprojects.src.python.hello.main/main.pex",
                ),
            ]),
        );
    }

    #[test]
    fn close_match_picks_best_candidate() {
        let candidates = ["src/unrelated/file.py", "src/unrelated"];
        assert_eq!(
            get_close_match("src/project/cmd.pex", candidates.iter(), 0.1),
            Some(&"src/unrelated/file.py"),
        );
        let no_match = ["xyz"];
        assert_eq!(get_close_match("abc", no_match.iter(), 0.1), None);
    }

    #[test]
    fn docker_style_globbing() {
        let cases: &[(&str, &str, bool)] = &[
            // `*` and `?` do not cross `/`, matching Go's `filepath.Match`.
            ("src.proj/nested/file.txt", "src.proj/*.txt", false),
            ("src.proj/bin_a.pex", "src.proj/*.pex", true),
            ("a/b", "a?b", false),
            ("axyb", "a**b", true),
            ("abc", "[a-c]bc", true),
            ("abc", "[!a]bc", false),
            ("[x", "[x", true),
            ("-", "[a-]", true),
            ("x", "[z-a]", false),
            ("ab", "a[b", false),
            ("aXb", "a[X-]b", true),
            ("ab", "a*b*", true),
            ("acb", "a*c?b", false),
        ];
        for (name, pattern, expected) in cases {
            assert_eq!(
                PathPattern::new(pattern).matches(name),
                *expected,
                "match({name:?}, {pattern:?})"
            );
        }
    }
}
