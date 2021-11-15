// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::Path;

use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;

use fs::{GlobExpansionConjunction, PathGlobs, PreparedPathGlobs, StrictGlobMatching};

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_function(wrap_pyfunction!(match_path_globs, m)?)?;
  m.add_function(wrap_pyfunction!(default_cache_path, m)?)?;
  Ok(())
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
