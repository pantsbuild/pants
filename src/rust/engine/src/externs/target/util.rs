// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt;
use std::hash::{Hash, Hasher};
use std::path::Path;
use std::sync::OnceLock;

use fnv::FnvHasher;

use pyo3::intern;
use pyo3::prelude::*;

static INVALID_FIELD_TYPE_EXCEPTION: OnceLock<Py<PyAny>> = OnceLock::new();
static INVALID_FIELD_CHOICE_EXCEPTION: OnceLock<Py<PyAny>> = OnceLock::new();
static INVALID_FIELD_EXCEPTION: OnceLock<Py<PyAny>> = OnceLock::new();
pub static GENERATE_SOURCES_REQUEST: OnceLock<Py<PyAny>> = OnceLock::new();

pub fn combine_hashes(hashes: &[isize]) -> isize {
    let mut hasher = FnvHasher::default();
    for h in hashes {
        h.hash(&mut hasher);
    }
    hasher.finish() as isize
}

pub fn import_target_attr<'py>(
    py: Python<'py>,
    cache: &OnceLock<Py<PyAny>>,
    name: &str,
) -> PyResult<Bound<'py, PyAny>> {
    if let Some(attr) = cache.get() {
        return Ok(attr.bind(py).clone());
    }
    let attr = py.import("pants.engine.target")?.getattr(name)?;
    let _ = cache.set(attr.clone().unbind());
    Ok(attr)
}

pub fn raise_invalid_field_type(
    py: Python,
    address: &Bound<PyAny>,
    alias: &str,
    raw_value: Option<&Bound<PyAny>>,
    expected_type_desc: &str,
) -> PyErr {
    match import_target_attr(
        py,
        &INVALID_FIELD_TYPE_EXCEPTION,
        "InvalidFieldTypeException",
    ) {
        Ok(exc_cls) => {
            let kwargs = pyo3::types::PyDict::new(py);
            let _ = kwargs.set_item("expected_type", expected_type_desc);
            match exc_cls.call((address, alias, raw_value), Some(&kwargs)) {
                Ok(exc) => PyErr::from_value(exc),
                Err(e) => e,
            }
        }
        Err(e) => e,
    }
}

pub fn validate_choices(
    py: Python,
    address: &Bound<PyAny>,
    alias: &str,
    values: &Bound<PyAny>,
    valid_choices: &Bound<PyAny>,
) -> PyResult<()> {
    let choices_set = pyo3::types::PySet::empty(py)?;
    if valid_choices.is_instance_of::<pyo3::types::PyTuple>() {
        for item in valid_choices.try_iter()? {
            choices_set.add(item?)?;
        }
    } else {
        for member in valid_choices.try_iter()? {
            let member = member?;
            choices_set.add(member.getattr(intern!(py, "value"))?)?;
        }
    }
    for choice in values.try_iter()? {
        let choice = choice?;
        if !choices_set.contains(&choice)? {
            let exc_cls = import_target_attr(
                py,
                &INVALID_FIELD_CHOICE_EXCEPTION,
                "InvalidFieldChoiceException",
            )?;
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("valid_choices", &choices_set)?;
            return Err(PyErr::from_value(
                exc_cls.call((address, alias, &choice), Some(&kwargs))?,
            ));
        }
    }
    Ok(())
}

/// Python-style repr for a string: `'foo'`
pub struct PyRepr<'a>(pub &'a str);

impl fmt::Display for PyRepr<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "'{}'", self.0)
    }
}

/// Python-style repr for a string list: `['a', 'b']`
pub struct PyReprList<'a, T: AsRef<str>>(pub &'a [T]);

impl<T: AsRef<str>> fmt::Display for PyReprList<'_, T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("[")?;
        for (i, s) in self.0.iter().enumerate() {
            if i > 0 {
                f.write_str(", ")?;
            }
            write!(f, "'{}'", s.as_ref())?;
        }
        f.write_str("]")
    }
}

/// Joins a directory path and name, mimicking Python's `os.path.join` semantics
/// where an absolute `name` resets the path.
pub fn join_path(dirpath: &str, name: &str) -> String {
    Path::new(dirpath)
        .join(name)
        .into_os_string()
        .into_string()
        .expect("joined path of UTF-8 components is UTF-8")
}

/// Prefixes a glob pattern with a directory path. Handles `!` exclusion globs.
pub fn prefix_glob(dirpath: &str, glob: &str) -> String {
    match glob.strip_prefix('!') {
        Some(rest) => format!("!{}", join_path(dirpath, rest)),
        None => join_path(dirpath, glob),
    }
}

pub fn raise_invalid_field(py: Python, msg: String) -> PyErr {
    match import_target_attr(py, &INVALID_FIELD_EXCEPTION, "InvalidFieldException") {
        Ok(exc_cls) => match exc_cls.call1((msg,)) {
            Ok(exc) => PyErr::from_value(exc),
            Err(e) => e,
        },
        Err(e) => e,
    }
}

#[pyclass(name = "_NoValue", from_py_object)]
#[derive(Clone)]
pub struct NoFieldValue;

#[pymethods]
impl NoFieldValue {
    fn __bool__(&self) -> bool {
        false
    }

    fn __repr__(&self) -> &'static str {
        "<NO_VALUE>"
    }
}

#[cfg(test)]
mod tests {
    use super::{join_path, prefix_glob};

    #[test]
    fn join_path_prefixes_relative_name() {
        assert_eq!(join_path("src/python", "foo.py"), "src/python/foo.py");
        assert_eq!(
            join_path("src/python", "a/b/foo.py"),
            "src/python/a/b/foo.py"
        );
    }

    #[test]
    fn join_path_empty_dirpath_returns_name() {
        assert_eq!(join_path("", "foo.py"), "foo.py");
        assert_eq!(join_path("", "a/b.py"), "a/b.py");
    }

    #[test]
    fn join_path_absolute_name_resets() {
        assert_eq!(join_path("src/python", "/abs/foo.py"), "/abs/foo.py");
        assert_eq!(join_path("", "/abs/foo.py"), "/abs/foo.py");
    }

    #[test]
    fn join_path_preserves_glob_syntax() {
        assert_eq!(join_path("src", "**/*.py"), "src/**/*.py");
        assert_eq!(join_path("src", "*.py"), "src/*.py");
    }

    #[test]
    fn prefix_glob_include() {
        assert_eq!(prefix_glob("src/python", "*.py"), "src/python/*.py");
        assert_eq!(prefix_glob("", "*.py"), "*.py");
    }

    #[test]
    fn prefix_glob_exclusion_keeps_bang_prefix() {
        assert_eq!(
            prefix_glob("src/python", "!ignore.py"),
            "!src/python/ignore.py"
        );
        assert_eq!(
            prefix_glob("src/python", "!**/*_test.py"),
            "!src/python/**/*_test.py"
        );
    }

    #[test]
    fn prefix_glob_exclusion_empty_dirpath() {
        assert_eq!(prefix_glob("", "!ignore.py"), "!ignore.py");
    }

    #[test]
    fn prefix_glob_exclusion_absolute_resets() {
        assert_eq!(
            prefix_glob("src/python", "!/abs/ignore.py"),
            "!/abs/ignore.py"
        );
    }
}
