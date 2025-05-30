// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::hash_map::DefaultHasher;
use std::fmt;
use std::hash::{Hash, Hasher};
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use itertools::Itertools;
use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyException, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedStr;
use pyo3::types::{PyIterator, PyString, PyTuple, PyType};

use fs::{
    DirectoryDigest, EMPTY_DIRECTORY_DIGEST, FilespecMatcher, GlobExpansionConjunction, PathGlobs,
    PathMetadata, StrictGlobMatching,
};
use hashing::{Digest, EMPTY_DIGEST, Fingerprint};
use store::Snapshot;

use crate::Failure;
use crate::python::PyComparedBool;

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyDigest>()?;
    m.add_class::<PyFileDigest>()?;
    m.add_class::<PySnapshot>()?;
    m.add_class::<PyMergeDigests>()?;
    m.add_class::<PyAddPrefix>()?;
    m.add_class::<PyRemovePrefix>()?;
    m.add_class::<PyFilespecMatcher>()?;
    m.add_class::<PyPathMetadataKind>()?;
    m.add_class::<PyPathMetadata>()?;
    m.add_class::<PyPathNamespace>()?;

    m.add("EMPTY_DIGEST", PyDigest(EMPTY_DIRECTORY_DIGEST.clone()))?;
    m.add("EMPTY_FILE_DIGEST", PyFileDigest(EMPTY_DIGEST))?;
    m.add("EMPTY_SNAPSHOT", PySnapshot(Snapshot::empty()))?;

    m.add_function(wrap_pyfunction!(default_cache_path, m)?)?;
    Ok(())
}

///
/// A marker indicating that a `StoreError` is being converted into a python exception, since retry
/// via #11331 needs to preserve `Failure` information across Python boundaries.
///
/// TODO: Any use of `PyErr::from(Failure::from(StoreError))` would trigger this same conversion,
/// so this method can eventually be replaced with direct conversion via `?`.
///
pub fn possible_store_missing_digest(e: store::StoreError) -> PyErr {
    let failure: Failure = e.into();
    failure.into()
}

#[pyclass(name = "Digest")]
#[derive(Clone, Debug, PartialEq, Eq)]
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
            .map_err(|e| PyValueError::new_err(format!("Invalid digest hex: {e}")))?;
        Ok(Self(DirectoryDigest::from_persisted_digest(Digest::new(
            fingerprint,
            serialized_bytes_length,
        ))))
    }

    fn __hash__(&self) -> u64 {
        self.0.as_digest().hash.prefix_hash()
    }

    fn __repr__(&self) -> String {
        format!("{self}")
    }

    fn __richcmp__(&self, other: &Bound<'_, PyDigest>, op: CompareOp) -> PyComparedBool {
        let other_digest = other.borrow();
        PyComparedBool(match op {
            CompareOp::Eq => Some(*self == *other_digest),
            CompareOp::Ne => Some(*self != *other_digest),
            _ => None,
        })
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
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PyFileDigest(pub Digest);

#[pymethods]
impl PyFileDigest {
    #[new]
    fn __new__(fingerprint: &str, serialized_bytes_length: usize) -> PyResult<Self> {
        let fingerprint = Fingerprint::from_hex_string(fingerprint)
            .map_err(|e| PyValueError::new_err(format!("Invalid file digest hex: {e}")))?;
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

    fn __richcmp__(&self, other: &Bound<'_, PyFileDigest>, op: CompareOp) -> PyComparedBool {
        let other_file_digest = other.borrow();
        PyComparedBool(match op {
            CompareOp::Eq => Some(*self == *other_file_digest),
            CompareOp::Ne => Some(*self != *other_file_digest),
            _ => None,
        })
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
    fn create_for_testing(
        _cls: &Bound<'_, PyType>,
        files: Vec<String>,
        dirs: Vec<String>,
    ) -> PyResult<Self> {
        Ok(Self(
            Snapshot::create_for_testing(files, dirs).map_err(PyException::new_err)?,
        ))
    }

    fn __hash__(&self) -> u64 {
        self.0.digest.hash.prefix_hash()
    }

    fn __repr__(&self) -> PyResult<String> {
        Ok(format!(
            "Snapshot(digest=({}, {}), dirs=({}), files=({}))",
            self.0.digest.hash.to_hex(),
            self.0.digest.size_bytes,
            self.0
                .directories()
                .into_iter()
                .map(|d| d.display().to_string())
                .collect::<Vec<_>>()
                .join(","),
            self.0
                .files()
                .into_iter()
                .map(|d| d.display().to_string())
                .collect::<Vec<_>>()
                .join(","),
        ))
    }

    fn __richcmp__(&self, other: &Bound<'_, PySnapshot>, op: CompareOp) -> PyComparedBool {
        let other_digest = other.borrow().0.digest;
        PyComparedBool(match op {
            CompareOp::Eq => Some(self.0.digest == other_digest),
            CompareOp::Ne => Some(self.0.digest != other_digest),
            _ => None,
        })
    }

    #[getter]
    fn digest(&self) -> PyDigest {
        PyDigest(self.0.clone().into())
    }

    #[getter]
    fn files<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        let files = self.0.files();
        PyTuple::new(
            py,
            files
                .into_iter()
                .map(|path| PyString::new(py, &path.to_string_lossy()))
                .collect::<Vec<_>>(),
        )
    }

    #[getter]
    fn dirs<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        let dirs = self.0.directories();
        PyTuple::new(
            py,
            dirs.into_iter()
                .map(|path| PyString::new(py, &path.to_string_lossy()))
                .collect::<Vec<_>>(),
        )
    }

    // NB: Prefix with underscore. The Python call will be hidden behind a helper which returns a much
    // richer type.
    fn _diff<'py>(
        &self,
        other: &Bound<'py, PySnapshot>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyTuple>> {
        let result = self.0.tree.diff(&other.borrow().0.tree);

        let into_tuple = |x: &Vec<PathBuf>| -> PyResult<Bound<'py, PyTuple>> {
            PyTuple::new(
                py,
                x.iter()
                    .map(|path| PyString::new(py, &path.to_string_lossy()))
                    .collect::<Vec<_>>(),
            )
        };

        PyTuple::new(
            py,
            vec![
                into_tuple(&result.our_unique_files)?,
                into_tuple(&result.our_unique_dirs)?,
                into_tuple(&result.their_unique_files)?,
                into_tuple(&result.their_unique_dirs)?,
                into_tuple(&result.changed_files)?,
            ],
        )
    }
}

#[pyclass(name = "MergeDigests")]
#[derive(Debug, PartialEq, Eq)]
pub struct PyMergeDigests(pub Vec<DirectoryDigest>);

#[pymethods]
impl PyMergeDigests {
    #[new]
    fn __new__(digests: &Bound<'_, PyAny>, _py: Python) -> PyResult<Self> {
        let digests: PyResult<Vec<DirectoryDigest>> = PyIterator::from_object(digests)?
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
        format!("MergeDigests([{digests}])")
    }

    fn __richcmp__(&self, other: &Bound<'_, PyMergeDigests>, op: CompareOp) -> PyComparedBool {
        let other = other.borrow();
        PyComparedBool(match op {
            CompareOp::Eq => Some(*self == *other),
            CompareOp::Ne => Some(*self != *other),
            _ => None,
        })
    }
}

#[pyclass(name = "AddPrefix")]
#[derive(Debug, PartialEq, Eq)]
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

    fn __richcmp__(&self, other: &Bound<'_, PyAddPrefix>, op: CompareOp) -> PyComparedBool {
        let other = other.borrow();
        PyComparedBool(match op {
            CompareOp::Eq => Some(*self == *other),
            CompareOp::Ne => Some(*self != *other),
            _ => None,
        })
    }
}

#[pyclass(name = "RemovePrefix")]
#[derive(Debug, PartialEq, Eq)]
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

    fn __richcmp__(&self, other: &Bound<'_, PyRemovePrefix>, op: CompareOp) -> PyComparedBool {
        let other = other.borrow();
        PyComparedBool(match op {
            CompareOp::Eq => Some(*self == *other),
            CompareOp::Ne => Some(*self != *other),
            _ => None,
        })
    }
}

// -----------------------------------------------------------------------------
// PathGlobs
// -----------------------------------------------------------------------------

struct PyPathGlobs(#[allow(dead_code)] PathGlobs);

impl<'py> FromPyObject<'py> for PyPathGlobs {
    fn extract_bound(obj: &Bound<'py, PyAny>) -> PyResult<Self> {
        let globs: Vec<String> = obj.getattr("globs")?.extract()?;

        let description_of_origin_field = obj.getattr("description_of_origin")?;
        let description_of_origin = if description_of_origin_field.is_none() {
            None
        } else {
            Some(description_of_origin_field.extract()?)
        };

        let match_behavior_str: PyBackedStr = obj
            .getattr("glob_match_error_behavior")?
            .getattr("value")?
            .extract()?;
        let match_behavior =
            StrictGlobMatching::create(match_behavior_str.as_ref(), description_of_origin)
                .map_err(PyValueError::new_err)?;

        let conjunction_str: PyBackedStr =
            obj.getattr("conjunction")?.getattr("value")?.extract()?;
        let conjunction = GlobExpansionConjunction::create(conjunction_str.as_ref())
            .map_err(PyValueError::new_err)?;

        Ok(PyPathGlobs(PathGlobs::new(
            globs,
            match_behavior,
            conjunction,
        )))
    }
}

// -----------------------------------------------------------------------------
// FilespecMatcher
// -----------------------------------------------------------------------------

#[pyclass(name = "FilespecMatcher")]
#[derive(Debug)]
pub struct PyFilespecMatcher(FilespecMatcher);

#[pymethods]
impl PyFilespecMatcher {
    #[new]
    fn __new__(includes: Vec<String>, excludes: Vec<String>, py: Python) -> PyResult<Self> {
        // Parsing the globs has shown up in benchmarks
        // (https://github.com/pantsbuild/pants/issues/16122), so we use py.allow_threads().
        let matcher = py.allow_threads(|| {
            FilespecMatcher::new(includes, excludes).map_err(PyValueError::new_err)
        })?;
        Ok(Self(matcher))
    }

    fn __hash__(&self) -> u64 {
        let mut s = DefaultHasher::new();
        self.0.include_globs().hash(&mut s);
        self.0.exclude_globs().hash(&mut s);
        s.finish()
    }

    fn __repr__(&self) -> String {
        let includes = self
            .0
            .include_globs()
            .iter()
            .map(|pattern| pattern.to_string())
            .join(", ");
        let excludes = self.0.exclude_globs().join(", ");
        format!("FilespecMatcher(includes=['{includes}'], excludes=[{excludes}])",)
    }

    fn __richcmp__(&self, other: &Bound<'_, PyFilespecMatcher>, op: CompareOp) -> PyComparedBool {
        let other = other.borrow();
        PyComparedBool(match op {
            CompareOp::Eq => Some(
                self.0.include_globs() == other.0.include_globs()
                    && self.0.exclude_globs() == other.0.exclude_globs(),
            ),
            CompareOp::Ne => Some(
                self.0.include_globs() != other.0.include_globs()
                    || self.0.exclude_globs() != other.0.exclude_globs(),
            ),
            _ => None,
        })
    }

    fn matches(&self, paths: Vec<String>, py: Python) -> PyResult<Vec<String>> {
        py.allow_threads(|| {
            Ok(paths
                .into_iter()
                .filter(|p| self.0.matches(Path::new(p)))
                .collect())
        })
    }
}

// -----------------------------------------------------------------------------
// Path Metadata
// -----------------------------------------------------------------------------

/// The kind of path (e.g., file, directory, symlink) as identified in `PathMetadata`
#[pyclass(name = "PathMetadataKind", rename_all = "UPPERCASE", eq)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PyPathMetadataKind {
    File,
    Directory,
    Symlink,
}

impl From<fs::PathMetadataKind> for PyPathMetadataKind {
    fn from(value: fs::PathMetadataKind) -> Self {
        match value {
            fs::PathMetadataKind::File => PyPathMetadataKind::File,
            fs::PathMetadataKind::Directory => PyPathMetadataKind::Directory,
            fs::PathMetadataKind::Symlink => PyPathMetadataKind::Symlink,
        }
    }
}

impl From<PyPathMetadataKind> for fs::PathMetadataKind {
    fn from(value: PyPathMetadataKind) -> Self {
        match value {
            PyPathMetadataKind::File => fs::PathMetadataKind::File,
            PyPathMetadataKind::Directory => fs::PathMetadataKind::Directory,
            PyPathMetadataKind::Symlink => fs::PathMetadataKind::Symlink,
        }
    }
}

/// Expanded version of `Stat` when access to additional filesystem attributes is necessary.
#[pyclass(name = "PathMetadata")]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PyPathMetadata(pub fs::PathMetadata);

#[pymethods]
impl PyPathMetadata {
    #[new]
    #[pyo3(signature = (
        path,
        kind,
        length,
        is_executable,
        unix_mode,
        accessed,
        created,
        modified,
        symlink_target
    ))]
    pub fn new(
        path: PathBuf,
        kind: PyPathMetadataKind,
        length: u64,
        is_executable: bool,
        unix_mode: Option<u32>,
        accessed: Option<SystemTime>,
        created: Option<SystemTime>,
        modified: Option<SystemTime>,
        symlink_target: Option<PathBuf>,
    ) -> Self {
        let this = PathMetadata {
            path,
            kind: kind.into(),
            length,
            is_executable,
            unix_mode,
            accessed,
            created,
            modified,
            symlink_target,
        };
        PyPathMetadata(this)
    }

    #[getter]
    pub fn path(&self) -> PyResult<String> {
        self.0
            .path
            .as_os_str()
            .to_str()
            .map(|s| s.to_string())
            .ok_or_else(|| {
                PyException::new_err(format!(
                    "Could not convert PyPathMetadata.path `{}` to UTF8.",
                    self.0.path.display()
                ))
            })
    }

    #[getter]
    pub fn kind(&self) -> PyResult<PyPathMetadataKind> {
        Ok(self.0.kind.into())
    }

    #[getter]
    pub fn length(&self) -> PyResult<u64> {
        Ok(self.0.length)
    }

    #[getter]
    pub fn is_executable(&self) -> PyResult<bool> {
        Ok(self.0.is_executable)
    }

    #[getter]
    pub fn unix_mode(&self) -> PyResult<Option<u32>> {
        Ok(self.0.unix_mode)
    }

    #[getter]
    pub fn accessed(&self) -> PyResult<Option<SystemTime>> {
        Ok(self.0.accessed)
    }

    #[getter]
    pub fn created(&self) -> PyResult<Option<SystemTime>> {
        Ok(self.0.created)
    }

    #[getter]
    pub fn modified(&self) -> PyResult<Option<SystemTime>> {
        Ok(self.0.modified)
    }

    #[getter]
    pub fn symlink_target(&self) -> PyResult<Option<String>> {
        let Some(symlink_target) = self.0.symlink_target.as_ref() else {
            return Ok(None);
        };
        Ok(Some(
            symlink_target
                .as_os_str()
                .to_str()
                .map(|s| s.to_string())
                .ok_or_else(|| {
                    PyException::new_err(format!(
                        "Could not convert PyPathMetadata.symlink_target `{}` to UTF8.",
                        symlink_target.display()
                    ))
                })?,
        ))
    }

    pub fn copy(&self) -> PyResult<Self> {
        Ok(self.clone())
    }

    fn __repr__(&self) -> String {
        format!("{:?}", self.0)
    }
}

/// The path's namespace (to separate buildroot and system paths)
#[pyclass(name = "PathNamespace", rename_all = "UPPERCASE", frozen, eq, hash)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum PyPathNamespace {
    Workspace,
    System,
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
                "Default cache path {s:?} could not be converted to a string."
            ))
        })
}
