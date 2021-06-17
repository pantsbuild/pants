// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::PathBuf;

use fs::{GlobExpansionConjunction, PathGlobs, PreparedPathGlobs, StrictGlobMatching};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::wrap_pyfunction;

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_function(wrap_pyfunction!(match_path_globs, m)?)?;
  Ok(())
}

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
        .filter(|p| path_globs.matches(&PathBuf::from(p)))
        .collect(),
    )
  })
}
