// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::exceptions::PyException;
use pyo3::prelude::*;

pub fn register(m: &PyModule) -> PyResult<()> {
  m.add_class::<PyExecutor>()?;
  Ok(())
}

#[pyclass]
#[derive(Debug, Clone)]
pub struct PyExecutor(pub task_executor::Executor);

#[pymethods]
impl PyExecutor {
  #[new]
  fn __new__(core_threads: usize, max_threads: usize) -> PyResult<Self> {
    task_executor::Executor::global(core_threads, max_threads)
      .map(PyExecutor)
      .map_err(PyException::new_err)
  }
}
