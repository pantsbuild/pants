// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use pyo3::basic::CompareOp;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use fs::DirectoryDigest;
use protos::gen::pants::cache::{
    dependency_inference_request, javascript_inference_metadata, JavascriptInferenceMetadata,
};

use crate::externs::fs::PyDigest;
use crate::python::PyComparedBool;

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyNativeDependenciesRequest>()?;
    m.add_class::<PyInferenceMetadata>()
}

#[pyclass(name = "InferenceMetadata")]
#[derive(Clone, Debug, PartialEq)]
pub struct PyInferenceMetadata(pub dependency_inference_request::Metadata);

fn as_import_patterns(
    dict: &Bound<'_, PyDict>,
) -> PyResult<Vec<javascript_inference_metadata::ImportPattern>> {
    dict.iter()
        .map(|(key, value)| {
            Ok(javascript_inference_metadata::ImportPattern {
                pattern: key.extract()?,
                replacements: value.extract()?,
            })
        })
        .collect()
}

#[pymethods]
impl PyInferenceMetadata {
    #[staticmethod]
    #[pyo3(signature = (package_root, import_patterns, config_root, paths))]
    fn javascript<'py>(
        package_root: String,
        import_patterns: &Bound<'py, PyDict>,
        config_root: Option<String>,
        paths: &Bound<'py, PyDict>,
    ) -> PyResult<Self> {
        let import_patterns = as_import_patterns(import_patterns)?;
        let paths = as_import_patterns(paths)?;
        Ok(Self(dependency_inference_request::Metadata::Js(
            JavascriptInferenceMetadata {
                package_root,
                import_patterns,
                config_root,
                paths,
            },
        )))
    }

    fn __richcmp__(&self, other: &Self, op: CompareOp) -> PyComparedBool {
        PyComparedBool(match op {
            CompareOp::Eq => Some(self == other),
            CompareOp::Ne => Some(self != other),
            _ => None,
        })
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

#[pyclass(name = "NativeDependenciesRequest")]
#[derive(Clone, Debug, PartialEq)]
pub struct PyNativeDependenciesRequest {
    pub directory_digest: DirectoryDigest,
    pub metadata: Option<dependency_inference_request::Metadata>,
}

#[pymethods]
impl PyNativeDependenciesRequest {
    #[new]
    #[pyo3(signature = (digest, metadata=None))]
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

    fn __richcmp__(&self, other: &Self, op: CompareOp) -> PyComparedBool {
        PyComparedBool(match op {
            CompareOp::Eq => Some(self == other),
            CompareOp::Ne => Some(self != other),
            _ => None,
        })
    }
}
