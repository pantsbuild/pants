// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::types::{PyModule, PyModuleMethods};
use pyo3::{pyfunction, wrap_pyfunction, Bound, PyResult, Python};

use crate::externs::PyGeneratorResponseNativeCall;
use crate::nodes::{task_get_context, RunId, SessionValues};

pub fn register(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(session_values, m)?)?;
    m.add_function(wrap_pyfunction!(run_id, m)?)?;

    Ok(())
}

#[pyfunction]
fn session_values() -> PyGeneratorResponseNativeCall {
    PyGeneratorResponseNativeCall::new(async move { task_get_context().get(SessionValues).await })
}

#[pyfunction]
fn run_id() -> PyGeneratorResponseNativeCall {
    PyGeneratorResponseNativeCall::new(async move { task_get_context().get(RunId).await })
}
