// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use super::PyExecutor;
use pyo3::create_exception;
use pyo3::exceptions::{PyBrokenPipeError, PyException, PyKeyboardInterrupt};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use task_executor::Executor;

create_exception!(native_engine_pyo3, PantsdConnectionException, PyException);
create_exception!(native_engine_pyo3, PantsdClientException, PyException);

#[pyclass]
pub struct PyNailgunClient {
  port: u16,
  executor: Executor,
}

#[pymethods]
impl PyNailgunClient {
  #[new]
  fn __new__(port: u16, py_executor: PyExecutor) -> Self {
    Self {
      port,
      executor: py_executor.executor,
    }
  }

  fn execute(&self, command: String, args: Vec<String>, env: &PyDict, py: Python) -> PyResult<i32> {
    use nailgun::NailgunClientError;

    let env_list: Vec<(String, String)> = env
      .items()
      .into_iter()
      .map(|kv_pair| kv_pair.extract::<(String, String)>())
      .collect::<Result<Vec<_>, _>>()?;

    py.allow_threads(|| {
      self
        .executor
        .block_on(nailgun::client_execute(self.port, command, args, env_list))
        .map_err(|e| match e {
          NailgunClientError::PreConnect(err_str) => PantsdConnectionException::new_err(err_str),
          NailgunClientError::PostConnect(err_str) => PantsdClientException::new_err(err_str),
          NailgunClientError::BrokenPipe => PyBrokenPipeError::new_err(""),
          NailgunClientError::KeyboardInterrupt => PyKeyboardInterrupt::new_err(""),
        })
    })
  }
}
