// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::hash::{Hash, Hasher};
use std::sync::OnceLock;

use fnv::FnvHasher;

use pyo3::intern;
use pyo3::prelude::*;

static INVALID_FIELD_TYPE_EXCEPTION: OnceLock<Py<PyAny>> = OnceLock::new();
static INVALID_FIELD_CHOICE_EXCEPTION: OnceLock<Py<PyAny>> = OnceLock::new();

pub fn combine_hashes(hashes: &[isize]) -> isize {
    let mut hasher = FnvHasher::default();
    for h in hashes {
        h.hash(&mut hasher);
    }
    hasher.finish() as isize
}

pub fn get_cached_exception<'py>(
    py: Python<'py>,
    cache: &OnceLock<Py<PyAny>>,
    name: &str,
) -> PyResult<Bound<'py, PyAny>> {
    if let Some(exc) = cache.get() {
        return Ok(exc.bind(py).clone());
    }
    let exc = py.import("pants.engine.target")?.getattr(name)?;
    let _ = cache.set(exc.clone().unbind());
    Ok(exc)
}

pub fn raise_invalid_field_type(
    py: Python,
    address: &Bound<PyAny>,
    alias: &str,
    raw_value: Option<&Bound<PyAny>>,
    expected_type_desc: &str,
) -> PyErr {
    match get_cached_exception(
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
            let exc_cls = get_cached_exception(
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
