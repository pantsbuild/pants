// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::hash_map::DefaultHasher;
use std::fmt;
use std::hash::{Hash, Hasher};
use std::path::{Path, PathBuf};

use itertools::Itertools;
use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyException, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyIterator, PyString, PyTuple, PyType};

use fs::{
  DirectoryDigest, GlobExpansionConjunction, PathGlobs, PreparedPathGlobs, StrictGlobMatching,
  EMPTY_DIRECTORY_DIGEST,
};
use hashing::{Digest, Fingerprint, EMPTY_DIGEST};
use store::Snapshot;

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_class::<PyDigest>()?;
  m.add_class::<PyFileDigest>()?;
  m.add_class::<PySnapshot>()?;
  m.add_class::<PyMergeDigests>()?;
  m.add_class::<PyAddPrefix>()?;
  m.add_class::<PyRemovePrefix>()?;

  m.add("EMPTY_DIGEST", PyDigest(EMPTY_DIRECTORY_DIGEST.clone()))?;
  m.add("EMPTY_FILE_DIGEST", PyFileDigest(EMPTY_DIGEST))?;
  m.add("EMPTY_SNAPSHOT", PySnapshot(Snapshot::empty()))?;

  m.add_function(wrap_pyfunction!(match_path_globs, m)?)?;
  m.add_function(wrap_pyfunction!(default_cache_path, m)?)?;
  Ok(())
}

#[pyclass(name = "Digest")]
#[derive(Clone, Debug, PartialEq)]
pub struct PyDigest(pub DirectoryDigest);

impl fmt::Display for PyDigest {
  fn fmt(&self, f: &mut fmt::Formatter) -> std::fmt::Result {
    let digest = self.0.as_digest();
    write!(
      f,
      "Digest('{}', {})",
      digest.hash.to_hex(),
      digest.size_bytes,
    )
  }
}

#[pymethods]
impl PyDigest {
  /// NB: This constructor is only safe for use in testing, or when there is some other guarantee
  /// that the Digest has been persisted.
  #[new]
  fn __new__(fingerprint: &str, serialized_bytes_length: usize) -> PyResult<Self> {
    let fingerprint = Fingerprint::from_hex_string(fingerprint)
      .map_err(|e| PyValueError::new_err(format!("Invalid digest hex: {}", e)))?;
    Ok(Self(DirectoryDigest::from_persisted_digest(Digest::new(
      fingerprint,
      serialized_bytes_length,
    ))))
  }

  fn __hash__(&self) -> u64 {
    self.0.as_digest().hash.prefix_hash()
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
    self.0.as_digest().hash.to_hex()
  }

  #[getter]
  fn serialized_bytes_length(&self) -> usize {
    self.0.as_digest().size_bytes
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
  ) -> PyResult<Self> {
    let snapshot =
      unsafe { Snapshot::create_for_testing_ffi(py_digest.0.as_digest(), files, dirs) };
    Ok(Self(snapshot.map_err(PyException::new_err)?))
  }

  fn __hash__(&self) -> u64 {
    self.0.digest.hash.prefix_hash()
  }

  fn __repr__(&self) -> PyResult<String> {
    let (dirs, files): (Vec<_>, Vec<_>) = self.0.tree.files_and_directories();

    Ok(format!(
      "Snapshot(digest=({}, {}), dirs=({}), files=({}))",
      self.0.digest.hash.to_hex(),
      self.0.digest.size_bytes,
      dirs
        .into_iter()
        .map(|d| d.display().to_string())
        .collect::<Vec<_>>()
        .join(","),
      files
        .into_iter()
        .map(|d| d.display().to_string())
        .collect::<Vec<_>>()
        .join(","),
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
    PyDigest(self.0.clone().into())
  }

  #[getter]
  fn files<'py>(&self, py: Python<'py>) -> &'py PyTuple {
    let (files, _) = self.0.tree.files_and_directories();
    PyTuple::new(
      py,
      files
        .into_iter()
        .map(|path| PyString::new(py, &path.to_string_lossy()))
        .collect::<Vec<_>>(),
    )
  }

  #[getter]
  fn dirs<'py>(&self, py: Python<'py>) -> &'py PyTuple {
    let (_, dirs) = self.0.tree.files_and_directories();
    PyTuple::new(
      py,
      dirs
        .into_iter()
        .map(|path| PyString::new(py, &path.to_string_lossy()))
        .collect::<Vec<_>>(),
    )
  }
}

#[pyclass(name = "MergeDigests")]
#[derive(Debug, PartialEq)]
pub struct PyMergeDigests(pub Vec<DirectoryDigest>);

#[pymethods]
impl PyMergeDigests {
  #[new]
  fn __new__(digests: &PyAny, py: Python) -> PyResult<Self> {
    let digests: PyResult<Vec<DirectoryDigest>> = PyIterator::from_object(py, digests)?
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
      .map(|d| format!("{}", PyDigest(d.clone())))
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
  pub digest: DirectoryDigest,
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
    self.digest.as_digest().hash.prefix_hash().hash(&mut s);
    self.prefix.hash(&mut s);
    s.finish()
  }

  fn __repr__(&self) -> String {
    format!(
      "AddPrefix('{}', {})",
      PyDigest(self.digest.clone()),
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
  pub digest: DirectoryDigest,
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
    self.digest.as_digest().hash.prefix_hash().hash(&mut s);
    self.prefix.hash(&mut s);
    s.finish()
  }

  fn __repr__(&self) -> String {
    format!(
      "RemovePrefix('{}', {})",
      PyDigest(self.digest.clone()),
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
