// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyAssertionError, PyValueError};
use pyo3::prelude::*;

use process_execution::{Platform, ProcessExecutionEnvironment, ProcessExecutionStrategy};

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_class::<PyProcessConfigFromEnvironment>()?;

  Ok(())
}

#[pyclass(name = "ProcessConfigFromEnvironment")]
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct PyProcessConfigFromEnvironment {
  pub environment: ProcessExecutionEnvironment,
}

#[pymethods]
impl PyProcessConfigFromEnvironment {
  #[new]
  fn __new__(
    environment_name: Option<String>,
    platform: String,
    docker_image: Option<String>,
    remote_execution: bool,
    remote_execution_extra_platform_properties: Vec<(String, String)>,
  ) -> PyResult<Self> {
    let platform = Platform::try_from(platform).map_err(PyValueError::new_err)?;
    let strategy = match (docker_image, remote_execution) {
      (None, true) => Ok(ProcessExecutionStrategy::RemoteExecution(
        remote_execution_extra_platform_properties,
      )),
      (None, false) => Ok(ProcessExecutionStrategy::Local),
      (Some(image), false) => Ok(ProcessExecutionStrategy::Docker(image)),
      (Some(_), true) => Err(PyAssertionError::new_err(
        "docker_image cannot be set at the same time as remote_execution",
      )),
    }?;
    Ok(Self {
      environment: ProcessExecutionEnvironment {
        name: environment_name,
        platform,
        strategy,
      },
    })
  }

  fn __hash__(&self) -> u64 {
    let mut s = DefaultHasher::new();
    self.environment.hash(&mut s);
    s.finish()
  }

  fn __repr__(&self) -> String {
    format!(
      "ProcessConfigFromEnvironment(environment={:?})",
      self.environment,
    )
  }

  fn __richcmp__(
    &self,
    other: &PyProcessConfigFromEnvironment,
    op: CompareOp,
    py: Python,
  ) -> PyObject {
    match op {
      CompareOp::Eq => (self == other).into_py(py),
      CompareOp::Ne => (self != other).into_py(py),
      _ => py.NotImplemented(),
    }
  }

  #[getter]
  fn platform(&self) -> String {
    self.environment.platform.into()
  }

  #[getter]
  fn remote_execution(&self) -> bool {
    matches!(
      self.environment.strategy,
      ProcessExecutionStrategy::RemoteExecution(_)
    )
  }

  #[getter]
  fn docker_image(&self) -> Option<String> {
    match &self.environment.strategy {
      ProcessExecutionStrategy::Docker(image) => Some(image.to_owned()),
      _ => None,
    }
  }

  #[getter]
  fn remote_execution_extra_platform_properties(&self) -> Vec<(String, String)> {
    match &self.environment.strategy {
      ProcessExecutionStrategy::RemoteExecution(properties) => properties.to_owned(),
      _ => vec![],
    }
  }
}
