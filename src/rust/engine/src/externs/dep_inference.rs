// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use pyo3::basic::CompareOp;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use pyo3::{IntoPy, PyObject, Python};

use fs::DirectoryDigest;
use protos::gen::pants::cache::{
  dependency_inference_request, javascript_inference_metadata, JavascriptInferenceMetadata,
};

use crate::externs::fs::PyDigest;

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_class::<PyNativeDependenciesRequest>()?;
  m.add_class::<PyInferenceMetadata>()
}

#[pyclass(name = "InferenceMetadata", weakref)]
#[derive(Clone, Debug, PartialEq)]
pub struct PyInferenceMetadata(pub dependency_inference_request::Metadata);

#[pymethods]
impl PyInferenceMetadata {
  #[staticmethod]
  fn javascript(package_root: String, import_patterns: &PyDict) -> PyResult<Self> {
    use javascript_inference_metadata::ImportPattern;
    let import_patterns: PyResult<Vec<ImportPattern>> = import_patterns
      .iter()
      .map(|(key, value)| {
        Ok(ImportPattern {
          pattern: key.extract()?,
          replacements: value.extract()?,
        })
      })
      .collect();
    Ok(Self(dependency_inference_request::Metadata::Js(
      JavascriptInferenceMetadata {
        package_root,
        import_patterns: import_patterns?,
      },
    )))
  }

  fn __richcmp__(&self, other: &Self, op: CompareOp, py: Python) -> PyObject {
    match op {
      CompareOp::Eq => (self == other).into_py(py),
      CompareOp::Ne => (self != other).into_py(py),
      _ => py.NotImplemented(),
    }
  }

  fn __repr__(&self) -> String {
    format!("InferenceMetadata({:?})", self.0)
  }

  fn __hash__(&self) -> u64 {
    let mut s = DefaultHasher::new();
    self.0.hash(&mut s);
    s.finish()
  }
}

#[pyclass(name = "NativeDependenciesRequest", weakref)]
#[derive(Clone, Debug, PartialEq)]
pub struct PyNativeDependenciesRequest {
  pub directory_digest: DirectoryDigest,
  pub metadata: Option<dependency_inference_request::Metadata>,
}

#[pymethods]
impl PyNativeDependenciesRequest {
  #[new]
  fn __new__(digest: PyDigest, metadata: Option<PyInferenceMetadata>) -> Self {
    Self {
      directory_digest: digest.0,
      metadata: metadata.map(|inner| inner.0),
    }
  }

  fn __hash__(&self) -> u64 {
    let mut s = DefaultHasher::new();
    self.directory_digest.hash(&mut s);
    self.metadata.hash(&mut s);
    s.finish()
  }

  fn __repr__(&self) -> String {
    format!(
      "NativeDependenciesRequest('{}', {:?})",
      PyDigest(self.directory_digest.clone()),
      self.metadata
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
