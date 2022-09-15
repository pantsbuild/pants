// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use pyo3::basic::CompareOp;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use process_execution::Platform;

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_class::<PyProcessConfigFromEnvironment>()?;

  Ok(())
}

#[pyclass(name = "ProcessConfigFromEnvironment")]
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PyProcessConfigFromEnvironment {
  pub platform: Platform,
  pub docker_image: Option<String>,
}

#[pymethods]
impl PyProcessConfigFromEnvironment {
  #[new]
  fn __new__(platform: String, docker_image: Option<String>) -> PyResult<Self> {
    let platform = Platform::try_from(platform).map_err(PyValueError::new_err)?;
    Ok(Self {
      platform,
      docker_image,
    })
  }

  fn __hash__(&self) -> u64 {
    let mut s = DefaultHasher::new();
    self.platform.hash(&mut s);
    self.docker_image.hash(&mut s);
    s.finish()
  }

  fn __repr__(&self) -> String {
    format!(
      "ProcessConfigFromEnvironment(platform={}, docker_image={})",
      String::from(self.platform),
      self.docker_image.as_ref().unwrap_or(&"None".to_owned())
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
  fn docker_image(&self) -> Option<String> {
    self.docker_image.clone()
  }
}
