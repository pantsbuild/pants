// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::exceptions::PyException;
use pyo3::prelude::*;

mod testutil;

#[pymodule]
fn native_engine_pyo3(_py: Python, m: &PyModule) -> PyResult<()> {
  m.add_class::<PyExecutor>()?;

  m.add_class::<self::testutil::PyStubCAS>()?;
  m.add_class::<self::testutil::PyStubCASBuilder>()?;

  Ok(())
}

#[pyclass]
#[derive(Debug, Clone)]
struct PyExecutor {
  executor: task_executor::Executor,
}

#[pymethods]
impl PyExecutor {
  #[new]
  fn __new__(core_threads: usize, max_threads: usize) -> PyResult<Self> {
    task_executor::Executor::global(core_threads, max_threads)
      .map(|executor| PyExecutor { executor })
      .map_err(PyException::new_err)
  }
}
