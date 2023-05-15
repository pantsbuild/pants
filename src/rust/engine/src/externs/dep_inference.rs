// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use pyo3::basic::CompareOp;
use pyo3::prelude::*;
use pyo3::{IntoPy, PyObject, Python};

use fs::DirectoryDigest;

use crate::externs::fs::PyDigest;

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_class::<PyNativeDependenciesRequest>()
}

#[pyclass(name = "NativeDependenciesRequest")]
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PyNativeDependenciesRequest {
  pub digest: DirectoryDigest,
  pub metadata: Option<String>,
}

#[pymethods]
impl PyNativeDependenciesRequest {
  #[new]
  fn __new__(digest: PyDigest, metadata: Option<&PyAny>, py: Python) -> PyResult<Self> {
    let metadata: Option<String> = if let Some(metadata) = metadata {
      py.import("json")?
        .getattr("dumps")?
        .call1((metadata,))?
        .extract()
    } else {
      Ok(None)
    }?;
    Ok(Self {
      digest: digest.0,
      metadata,
    })
  }

  fn __hash__(&self) -> u64 {
    let mut s = DefaultHasher::new();
    self.digest.as_digest().hash.prefix_hash().hash(&mut s);
    self.metadata.hash(&mut s);
    s.finish()
  }

  fn __repr__(&self) -> String {
    format!(
      "NativeDependenciesRequest('{}', {})",
      PyDigest(self.digest.clone()),
      self
        .metadata
        .as_ref()
        .map_or_else(|| "None", |string| string.as_str())
    )
  }

  fn __richcmp__(&self, other: &Self, op: CompareOp, py: Python) -> PyObject {
    match op {
      CompareOp::Eq => (self == other).into_py(py),
      CompareOp::Ne => (self != other).into_py(py),
      _ => py.NotImplemented(),
    }
  }
}
