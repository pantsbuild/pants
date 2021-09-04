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
    // TODO: Find a better way to propagate the Source.
    Ok((opt_val.value, format!("{:?}", opt_val.source)))
  }
}
