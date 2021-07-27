// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::Path;

use pyo3::basic::CompareOp;
use pyo3::class::basic::PyObjectProtocol;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyString, PyTuple, PyType};

use fs::PathStat;
use fs::{GlobExpansionConjunction, PathGlobs, PreparedPathGlobs, StrictGlobMatching};
use hashing::{Digest, Fingerprint};
use store::Snapshot;

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_function(wrap_pyfunction!(check_fs_python_types_load, m)?)?;
  m.add_function(wrap_pyfunction!(match_path_globs, m)?)?;
  m.add_function(wrap_pyfunction!(default_cache_path, m)?)?;
  m.add_class::<PyDigest>()?;
  m.add_class::<PySnapshot>()?;
  Ok(())
}

#[pyfunction]
#[allow(unused_variables)]
fn check_fs_python_types_load(path_globs: PyPathGlobs) {}

// -----------------------------------------------------------------------------
// PathGlobs
// -----------------------------------------------------------------------------

struct PyPathGlobs(PathGlobs);

impl PyPathGlobs {
  fn parse(self) -> PyResult<PreparedPathGlobs> {
    self.0.clone().parse().map_err(|e| {
      PyValueError::new_err(format!(
        "Failed to parse PathGlobs: {:?}\n\nError: {}",
        self.0, e
      ))
    })
  }
}

impl<'source> FromPyObject<'source> for PyPathGlobs {
  fn extract(obj: &'source PyAny) -> PyResult<Self> {
    let globs: Vec<String> = obj.getattr("globs")?.extract()?;

    let description_of_origin_field: String = obj.getattr("description_of_origin")?.extract()?;
    let description_of_origin = if description_of_origin_field.is_empty() {
      None
    } else {
      Some(description_of_origin_field)
    };

    let match_behavior_str: &str = obj
      .getattr("glob_match_error_behavior")?
      .getattr("value")?
      .extract()?;
    let match_behavior = StrictGlobMatching::create(match_behavior_str, description_of_origin)
      .map_err(PyValueError::new_err)?;

    let conjunction_str: &str = obj.getattr("conjunction")?.getattr("value")?.extract()?;
    let conjunction =
      GlobExpansionConjunction::create(conjunction_str).map_err(PyValueError::new_err)?;

    Ok(PyPathGlobs(PathGlobs::new(
      globs,
      match_behavior,
      conjunction,
    )))
  }
}

#[pyfunction]
fn match_path_globs(
  py_path_globs: PyPathGlobs,
  paths: Vec<String>,
  py: Python,
) -> PyResult<Vec<String>> {
  py.allow_threads(|| {
    let path_globs = py_path_globs.parse()?;
    Ok(
      paths
        .into_iter()
        .filter(|p| path_globs.matches(&Path::new(p)))
        .collect(),
    )
  })
}

// -----------------------------------------------------------------------------
// Digest
// -----------------------------------------------------------------------------

#[pyclass]
#[derive(Clone)]
struct PyDigest(Digest);

#[pymethods]
impl PyDigest {
  #[new]
  fn __new__(fingerprint: &str, serialized_bytes_length: usize) -> PyResult<Self> {
    let fingerprint = Fingerprint::from_hex_string(fingerprint)
      .map_err(|e| PyValueError::new_err(format!("Invalid digest hex: {}", e)))?;
    Ok(Self(Digest::new(fingerprint, serialized_bytes_length)))
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

#[pyproto]
impl PyObjectProtocol for PyDigest {
  fn __richcmp__(&self, other: PyRef<PyDigest>, op: CompareOp) -> Py<PyAny> {
    let py = other.py();
    match op {
      CompareOp::Eq => (self.0 == other.0).into_py(py),
      CompareOp::Ne => (self.0 != other.0).into_py(py),
      _ => py.NotImplemented(),
    }
  }

  fn __hash__(&self) -> u64 {
    self.0.hash.prefix_hash()
  }

  fn __repr__(&self) -> String {
    format!("Digest('{}', {})", self.0.hash.to_hex(), self.0.size_bytes)
  }
}

// -----------------------------------------------------------------------------
// Snapshot
// -----------------------------------------------------------------------------

#[pyclass]
struct PySnapshot(Snapshot);

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

  #[getter]
  fn digest(&self) -> PyDigest {
    PyDigest(self.0.digest)
  }

  #[getter]
  fn files(&self, py: Python) -> Py<PyTuple> {
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
    PyTuple::new(py, files).into()
  }

  #[getter]
  fn dirs(&self, py: Python) -> Py<PyTuple> {
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
    PyTuple::new(py, dirs).into()
  }
}

#[pyproto]
impl PyObjectProtocol for PySnapshot {
  fn __richcmp__(&self, other: PyRef<PySnapshot>, op: CompareOp) -> Py<PyAny> {
    let py = other.py();
    match op {
      CompareOp::Eq => (self.0.digest == other.0.digest).into_py(py),
      CompareOp::Ne => (self.0.digest != other.0.digest).into_py(py),
      _ => py.NotImplemented(),
    }
  }

  fn __hash__(&self) -> u64 {
    self.0.digest.hash.prefix_hash()
  }
}

// -----------------------------------------------------------------------------
// Utils
// -----------------------------------------------------------------------------

#[pyfunction]
fn default_cache_path() -> PyResult<String> {
  fs::default_cache_path()
    .into_os_string()
    .into_string()
    .map_err(|s| {
      PyTypeError::new_err(format!(
        "Default cache path {:?} could not be converted to a string.",
        s
      ))
    })
}
