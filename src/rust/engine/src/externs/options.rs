// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;

use pyo3::exceptions;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};

use options::{Args, Env, OptionId, OptionParser, Scope};

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_class::<PyOptionId>()?;
  m.add_class::<PyOptionParser>()?;
  Ok(())
}

#[pyclass]
struct PyOptionId(OptionId);

#[pymethods]
impl PyOptionId {
  #[new]
  #[args(components = "*", scope = "None", switch = "None")]
  fn __new__(
    components: &PyTuple,
    scope: Option<String>,
    switch: Option<String>,
  ) -> PyResult<Self> {
    let components = components
      .iter()
      .map(|c| c.extract::<String>())
      .collect::<Result<Vec<_>, _>>()?;
    let scope = scope.map(|s| Scope::named(&s)).unwrap_or(Scope::Global);
    let switch = match switch {
      Some(switch) if switch.len() == 1 => switch.chars().next(),
      None => None,
      Some(s) => {
        return Err(exceptions::PyValueError::new_err(format!(
          "Switch value should contain a single character, but was: {}",
          s
        )))
      }
    };
    let option_id = OptionId::new(scope, components.into_iter(), switch)
      .map_err(exceptions::PyValueError::new_err)?;
    Ok(Self(option_id))
  }
}

#[pyclass]
struct PyOptionParser(OptionParser);

#[pymethods]
impl PyOptionParser {
  #[new]
  fn __new__(env: &PyDict, args: Vec<String>) -> PyResult<Self> {
    let env = env
      .items()
      .into_iter()
      .map(|kv_pair| kv_pair.extract::<(String, String)>())
      .collect::<Result<HashMap<_, _>, _>>()?;

    let option_parser = OptionParser::new(Env::new(env), Args::new(args))
      .map_err(exceptions::PyValueError::new_err)?;
    Ok(Self(option_parser))
  }

  fn parse_bool(&self, option_id: &PyOptionId, default: bool) -> PyResult<(bool, String)> {
    let opt_val = self
      .0
      .parse_bool(&option_id.0, default)
      .map_err(exceptions::PyException::new_err)?;
    Ok((opt_val.value, format!("{:?}", opt_val.source)))
  }

  fn parse_int(&self, option_id: &PyOptionId, default: i64) -> PyResult<(i64, String)> {
    let opt_val = self
      .0
      .parse_int(&option_id.0, default)
      .map_err(exceptions::PyException::new_err)?;
    Ok((opt_val.value, format!("{:?}", opt_val.source)))
  }

  fn parse_int_optional(
    &self,
    option_id: &PyOptionId,
    default: Option<i64>,
  ) -> PyResult<(Option<i64>, String)> {
    // Parse with an arbitrary default, and replace with the optional default if the Source
    // indicates that we defaulted.
    let opt_val = self
      .0
      .parse_int(&option_id.0, 0)
      .map_err(exceptions::PyException::new_err)?;
    if opt_val.source == Source::Default {
      Ok((default, format!("{:?}", Source::Default)))
    } else {
      Ok((Some(opt_val.value), format!("{:?}", opt_val.source)))
    }
  }

  fn parse_float(&self, option_id: &PyOptionId, default: f64) -> PyResult<(f64, String)> {
    let opt_val = self
      .0
      .parse_float(&option_id.0, default)
      .map_err(exceptions::PyException::new_err)?;
    Ok((opt_val.value, format!("{:?}", opt_val.source)))
  }

  fn parse_float_optional(
    &self,
    option_id: &PyOptionId,
    default: Option<f64>,
  ) -> PyResult<(Option<f64>, String)> {
    // Parse with an arbitrary default, and replace with the optional default if the Source
    // indicates that we defaulted.
    let opt_val = self
      .0
      .parse_float(&option_id.0, 0.0)
      .map_err(exceptions::PyException::new_err)?;
    if opt_val.source == Source::Default {
      Ok((default, format!("{:?}", Source::Default)))
    } else {
      Ok((Some(opt_val.value), format!("{:?}", opt_val.source)))
    }
  }

  fn parse_string(&self, option_id: &PyOptionId, default: &str) -> PyResult<(String, String)> {
    let opt_val = self
      .0
      .parse_string(&option_id.0, &default)
      .map_err(exceptions::PyException::new_err)?;
    Ok((opt_val.value, format!("{:?}", opt_val.source)))
  }

  fn parse_string_list(
    &self,
    option_id: &PyOptionId,
    default: Vec<&str>,
  ) -> PyResult<(Vec<String>, String)> {
    let opt_val = self
      .0
      .parse_string_list(&option_id.0, &default)
      .map_err(exceptions::PyException::new_err)?;
    Ok((opt_val.value, format!("{:?}", opt_val.source)))
  }
}
