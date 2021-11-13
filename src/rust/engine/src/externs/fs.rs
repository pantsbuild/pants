// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use either::Either;
use itertools::Itertools;
use pyo3::basic::CompareOp;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyString, PyTuple, PyType};

use fs::PathStat;
use hashing::{Digest, Fingerprint};
use store::Snapshot;

// -----------------------------------------------------------------------------
// Digest
// -----------------------------------------------------------------------------

#[pyclass]
#[derive(Clone)]
pub struct PyDigest(pub Digest);

#[pymethods]
impl PyDigest {
  #[new]
  fn __new__(fingerprint: &str, serialized_bytes_length: usize) -> PyResult<Self> {
    let fingerprint = Fingerprint::from_hex_string(fingerprint)
      .map_err(|e| PyValueError::new_err(format!("Invalid digest hex: {}", e)))?;
    Ok(Self(Digest::new(fingerprint, serialized_bytes_length)))
  }

  fn __hash__(&self) -> u64 {
    self.0.hash.prefix_hash()
  }

  fn __repr__(&self) -> String {
    format!("Digest('{}', {})", self.0.hash.to_hex(), self.0.size_bytes)
  }

  fn __richcmp__(&self, other: &PyDigest, op: CompareOp, py: Python) -> PyObject {
    match op {
      CompareOp::Eq => (self.0 == other.0).into_py(py),
      CompareOp::Ne => (self.0 != other.0).into_py(py),
      _ => py.NotImplemented(),
    }
  }

  #[getter]
  fn fingerprint(&self) -> String {
    self.0.hash.to_hex()
  }

  #[getter]
  fn serialized_bytes_length(&self) -> usize {
    self.0.size_bytes
  }
}

// -----------------------------------------------------------------------------
// Snapshot
// -----------------------------------------------------------------------------

#[pyclass]
pub struct PySnapshot(pub Snapshot);

#[pymethods]
impl PySnapshot {
  #[new]
  fn __new__() -> Self {
    Self(Snapshot::empty())
  }

  #[classmethod]
  fn _create_for_testing(
    _cls: &PyType,
    py_digest: PyDigest,
    files: Vec<String>,
    dirs: Vec<String>,
  ) -> Self {
    let snapshot = unsafe { Snapshot::create_for_testing_ffi(py_digest.0, files, dirs) };
    Self(snapshot)
  }

  fn __hash__(&self) -> u64 {
    self.0.digest.hash.prefix_hash()
  }

  fn __repr__(&self) -> PyResult<String> {
    let (dirs, files): (Vec<_>, Vec<_>) = self.0.path_stats.iter().partition_map(|ps| match ps {
      PathStat::Dir { path, .. } => Either::Left(path.to_string_lossy()),
      PathStat::File { path, .. } => Either::Right(path.to_string_lossy()),
    });

    Ok(format!(
      "Snapshot(digest=({}, {}), dirs=({}), files=({}))",
      self.0.digest.hash.to_hex(),
      self.0.digest.size_bytes,
      dirs.join(","),
      files.join(",")
    ))
  }

  fn __richcmp__(&self, other: &PySnapshot, op: CompareOp, py: Python) -> PyObject {
    match op {
      CompareOp::Eq => (self.0.digest == other.0.digest).into_py(py),
      CompareOp::Ne => (self.0.digest != other.0.digest).into_py(py),
      _ => py.NotImplemented(),
    }
  }

  #[getter]
  fn digest(&self) -> PyDigest {
    PyDigest(self.0.digest)
  }

  #[getter]
  fn files<'py>(&self, py: Python<'py>) -> &'py PyTuple {
    let files = self
      .0
      .path_stats
      .iter()
      .filter_map(|ps| match ps {
        PathStat::File { path, .. } => path.to_str(),
        _ => None,
      })
      .map(|ps| PyString::new(py, ps))
      .collect::<Vec<_>>();
    PyTuple::new(py, files)
  }

  #[getter]
  fn dirs<'py>(&self, py: Python<'py>) -> &'py PyTuple {
    let dirs = self
      .0
      .path_stats
      .iter()
      .filter_map(|ps| match ps {
        PathStat::Dir { path, .. } => path.to_str(),
        _ => None,
      })
      .map(|ps| PyString::new(py, ps))
      .collect::<Vec<_>>();
    PyTuple::new(py, dirs)
  }
}
