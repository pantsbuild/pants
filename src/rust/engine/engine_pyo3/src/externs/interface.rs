// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::exceptions::PyException;
use pyo3::prelude::*;

mod nailgun;
mod stdio;
mod testutil;

#[cfg(test)]
mod stdio_tests;

#[pymodule]
fn native_engine_pyo3(py: Python, m: &PyModule) -> PyResult<()> {
  self::nailgun::register(py, m)?;
  self::stdio::register(m)?;
  self::testutil::register(m)?;

  m.add_class::<PyExecutor>()?;

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
