// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::Arc;

use parking_lot::Mutex;
use pyo3::exceptions::PyAssertionError;
use pyo3::prelude::*;
use pyo3::types::PyType;

use crate::externs::interface::scheduler::PyExecutor;
use testutil_mock::{StubCAS, StubCASBuilder};

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_class::<PyStubCAS>()?;
  m.add_class::<PyStubCASBuilder>()?;
  Ok(())
}

#[pyclass]
struct PyStubCASBuilder(Arc<Mutex<Option<StubCASBuilder>>>);

#[pymethods]
impl PyStubCASBuilder {
  fn always_errors(&mut self) -> PyResult<PyStubCASBuilder> {
    let mut builder_opt = self.0.lock();
    let builder = builder_opt
      .take()
      .ok_or_else(|| PyAssertionError::new_err("Unable to unwrap StubCASBuilder"))?;
    *builder_opt = Some(builder.always_errors());
    Ok(PyStubCASBuilder(self.0.clone()))
  }

  fn build(&mut self, py_executor: PyExecutor) -> PyResult<PyStubCAS> {
    let mut builder_opt = self.0.lock();
    let builder = builder_opt
      .take()
      .ok_or_else(|| PyAssertionError::new_err("Unable to unwrap StubCASBuilder"))?;
    // NB: A Tokio runtime must be used when building StubCAS.
    py_executor.0.enter(|| Ok(PyStubCAS(builder.build())))
  }
}

#[pyclass]
struct PyStubCAS(StubCAS);

#[pymethods]
impl PyStubCAS {
  #[classmethod]
  fn builder(_cls: &PyType) -> PyStubCASBuilder {
    let builder = Arc::new(Mutex::new(Some(StubCAS::builder())));
    PyStubCASBuilder(builder)
  }

  #[getter]
  fn address(&self) -> String {
    self.0.address()
  }
}
