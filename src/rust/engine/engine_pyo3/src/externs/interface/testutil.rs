// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::Arc;

use super::PyExecutor;
use parking_lot::Mutex;
use pyo3::exceptions::PyAssertionError;
use pyo3::prelude::*;
use pyo3::types::PyType;
use testutil_mock::{StubCAS, StubCASBuilder};

#[pyclass]
pub struct PyStubCASBuilder {
  builder: Arc<Mutex<Option<StubCASBuilder>>>,
}

#[pymethods]
impl PyStubCASBuilder {
  fn always_errors(&mut self) -> PyResult<PyStubCASBuilder> {
    let mut builder_opt = self.builder.lock();
    let builder = builder_opt
      .take()
      .ok_or_else(|| PyAssertionError::new_err("Unable to unwrap StubCASBuilder"))?;
    *builder_opt = Some(builder.always_errors());
    Ok(PyStubCASBuilder {
      builder: self.builder.clone(),
    })
  }

  fn build(&mut self, py_executor: PyExecutor) -> PyResult<PyStubCAS> {
    let mut builder_opt = self.builder.lock();
    let builder = builder_opt
      .take()
      .ok_or_else(|| PyAssertionError::new_err("Unable to unwrap StubCASBuilder"))?;
    // NB: A Tokio runtime must be used when building StubCAS.
    py_executor.executor.enter(|| {
      Ok(PyStubCAS {
        stub_cas: builder.build(),
      })
    })
  }
}

#[pyclass]
pub struct PyStubCAS {
  stub_cas: StubCAS,
}

#[pymethods]
impl PyStubCAS {
  #[classmethod]
  fn builder(_cls: &PyType) -> PyStubCASBuilder {
    let builder = Arc::new(Mutex::new(Some(StubCAS::builder())));
    PyStubCASBuilder { builder }
  }

  #[getter]
  fn address(&self) -> String {
    self.stub_cas.address()
  }
}
