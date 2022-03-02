// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::hash_map::DefaultHasher;
use std::fmt;
use std::hash::{Hash, Hasher};
use std::path::{Path, PathBuf};

use either::Either;
use itertools::Itertools;
use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyIterator, PyString, PyTuple, PyType};

use fs::{GlobExpansionConjunction, PathGlobs, PathStat, PreparedPathGlobs, StrictGlobMatching};
use hashing::{Digest, Fingerprint, EMPTY_DIGEST};
use store::Snapshot;

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_class::<PyDigest>()?;
  m.add_class::<PyFileDigest>()?;
  m.add_class::<PySnapshot>()?;
  m.add_class::<PyMergeDigests>()?;
  m.add_class::<PyAddPrefix>()?;
  m.add_class::<PyRemovePrefix>()?;

  m.add("EMPTY_DIGEST", PyDigest(EMPTY_DIGEST))?;
  m.add("EMPTY_FILE_DIGEST", PyFileDigest(EMPTY_DIGEST))?;
  m.add("EMPTY_SNAPSHOT", PySnapshot(Snapshot::empty()))?;

  m.add_function(wrap_pyfunction!(match_path_globs, m)?)?;
  m.add_function(wrap_pyfunction!(default_cache_path, m)?)?;
  Ok(())
}

#[pyclass(name = "Digest")]
#[derive(Clone, Debug, PartialEq)]
pub struct PyDigest(pub Digest);

impl fmt::Display for PyDigest {
  fn fmt(&self, f: &mut fmt::Formatter) -> std::fmt::Result {
    write!(
      f,
      "Digest('{}', {})",
      self.0.hash.to_hex(),
      self.0.size_bytes
    )
  }
}

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
    format!("{}", self)
  }

  fn __richcmp__(&self, other: &PyDigest, op: CompareOp, py: Python) -> PyObject {
    match op {
      CompareOp::Eq => (self == other).into_py(py),
      CompareOp::Ne => (self != other).into_py(py),
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

#[pyclass(name = "FileDigest")]
#[derive(Debug, Clone, PartialEq)]
pub struct PyFileDigest(pub Digest);

#[pymethods]
impl PyFileDigest {
  #[new]
  fn __new__(fingerprint: &str, serialized_bytes_length: usize) -> PyResult<Self> {
    let fingerprint = Fingerprint::from_hex_string(fingerprint)
      .map_err(|e| PyValueError::new_err(format!("Invalid file digest hex: {}", e)))?;
    Ok(Self(Digest::new(fingerprint, serialized_bytes_length)))
  }

  fn __hash__(&self) -> u64 {
    self.0.hash.prefix_hash()
  }

  fn __repr__(&self) -> String {
    format!(
      "FileDigest('{}', {})",
      self.0.hash.to_hex(),
      self.0.size_bytes
    )
  }

  fn __richcmp__(&self, other: &PyFileDigest, op: CompareOp, py: Python) -> PyObject {
    match op {
      CompareOp::Eq => (self == other).into_py(py),
      CompareOp::Ne => (self != other).into_py(py),
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

#[pyclass(name = "Snapshot")]
pub struct PySnapshot(pub Snapshot);

#[pymethods]
impl PySnapshot {
  #[classmethod]
  fn _unsafe_create(
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

#[pyclass(name = "MergeDigests")]
#[derive(Debug, PartialEq)]
pub struct PyMergeDigests(pub Vec<Digest>);

#[pymethods]
impl PyMergeDigests {
  #[new]
  fn __new__(digests: &PyAny, py: Python) -> PyResult<Self> {
    let digests: PyResult<Vec<Digest>> = PyIterator::from_object(py, digests)?
      .map(|v| {
        let py_digest = v?.extract::<PyDigest>()?;
        Ok(py_digest.0)
      })
      .collect();
    Ok(Self(digests?))
  }

  fn __hash__(&self) -> u64 {
    let mut s = DefaultHasher::new();
    self.0.hash(&mut s);
    s.finish()
  }

  fn __repr__(&self) -> String {
    let digests = self
      .0
      .iter()
      .map(|d| format!("{}", PyDigest(*d)))
      .join(", ");
    format!("MergeDigests([{}])", digests)
  }

  fn __richcmp__(&self, other: &PyMergeDigests, op: CompareOp, py: Python) -> PyObject {
    match op {
      CompareOp::Eq => (self == other).into_py(py),
      CompareOp::Ne => (self != other).into_py(py),
      _ => py.NotImplemented(),
    }
  }
}

#[pyclass(name = "AddPrefix")]
#[derive(Debug, PartialEq)]
pub struct PyAddPrefix {
  pub digest: Digest,
  pub prefix: PathBuf,
}

#[pymethods]
impl PyAddPrefix {
  #[new]
  fn __new__(digest: PyDigest, prefix: PathBuf) -> Self {
    Self {
      digest: digest.0,
      prefix,
    }
  }

  fn __hash__(&self) -> u64 {
    let mut s = DefaultHasher::new();
    self.digest.hash.prefix_hash().hash(&mut s);
    self.prefix.hash(&mut s);
    s.finish()
  }

  fn __repr__(&self) -> String {
    format!(
      "AddPrefix('{}', {})",
      PyDigest(self.digest),
      self.prefix.display()
    )
  }

  fn __richcmp__(&self, other: &PyAddPrefix, op: CompareOp, py: Python) -> PyObject {
    match op {
      CompareOp::Eq => (self == other).into_py(py),
      CompareOp::Ne => (self != other).into_py(py),
      _ => py.NotImplemented(),
    }
  }
}

#[pyclass(name = "RemovePrefix")]
#[derive(Debug, PartialEq)]
pub struct PyRemovePrefix {
  pub digest: Digest,
  pub prefix: PathBuf,
}

#[pymethods]
impl PyRemovePrefix {
  #[new]
  fn __new__(digest: PyDigest, prefix: PathBuf) -> Self {
    Self {
      digest: digest.0,
      prefix,
    }
  }

  fn __hash__(&self) -> u64 {
    let mut s = DefaultHasher::new();
    self.digest.hash.prefix_hash().hash(&mut s);
    self.prefix.hash(&mut s);
    s.finish()
  }

  fn __repr__(&self) -> String {
    format!(
      "RemovePrefix('{}', {})",
      PyDigest(self.digest),
      self.prefix.display()
    )
  }

  fn __richcmp__(&self, other: &PyRemovePrefix, op: CompareOp, py: Python) -> PyObject {
    match op {
      CompareOp::Eq => (self == other).into_py(py),
      CompareOp::Ne => (self != other).into_py(py),
      _ => py.NotImplemented(),
    }
  }
}

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

    let description_of_origin_field = obj.getattr("description_of_origin")?;
    let description_of_origin = if description_of_origin_field.is_none() {
      None
    } else {
      Some(description_of_origin_field.extract()?)
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
        .filter(|p| path_globs.matches(Path::new(p)))
        .collect(),
    )
  })
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
