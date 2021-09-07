// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;

use pyo3::exceptions;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyFunction, PyList, PyTuple};

use options::{Args, Env, OptionId, OptionParser, Scope, Source};

use crate::Key;

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_class::<PyOptionId>()?;
  m.add_class::<PyOptionParser>()?;
  Ok(())
}

fn toml_value_to_py_object(py: Python, value: toml::Value) -> PyResult<PyObject> {
  use toml::Value::*;
  let res = match value {
    String(s) => s.into_py(py),
    Integer(i) => i.into_py(py),
    Float(f) => f.into_py(py),
    Boolean(b) => b.into_py(py),
    Datetime(_) => {
      return Err(exceptions::PyException::new_err(
        "datetime type not supported.",
      ))
    }
    Array(a) => {
      let list = PyList::empty(py);
      for m in a {
        list.append(toml_value_to_py_object(py, m)?)?;
      }
      list.into_py(py)
    }
    Table(t) => {
      let dict = PyDict::new(py);
      for (k, v) in t {
        dict.set_item(k, toml_value_to_py_object(py, v)?)?;
      }
      dict.into_py(py)
    }
  };

  Ok(res)
}

#[pyclass]
struct PyOptionId(OptionId);

#[pymethods]
impl PyOptionId {
  #[new]
  #[pyo3(signature = (*components, scope = None, switch = None))]
  fn __new__(components: &PyTuple, scope: Option<&str>, switch: Option<&str>) -> PyResult<Self> {
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

  fn parse_from_string<'a>(
    &self,
    option_id: &PyOptionId,
    default: &'a PyAny,
    parser: &'a PyFunction,
  ) -> PyResult<(&'a PyAny, String)> {
    let opt_val = self
      .0
      .parse_from_string(&option_id.0, default, |s| {
        parser.call((s,), None).map_err(|e| e.to_string())
      })
      .map_err(exceptions::PyException::new_err)?;
    Ok((opt_val.value, format!("{:?}", opt_val.source)))
  }

  fn parse_from_string_list<'a>(
    &self,
    py: Python<'a>,
    option_id: &PyOptionId,
    default: Vec<&'a PyAny>,
    member_parser: &'a PyFunction,
  ) -> PyResult<(Vec<&'a PyAny>, String)> {
    let default = default
      .into_iter()
      .map(|s| Key::from_value(s.extract()?))
      .collect::<Result<Vec<Key>, _>>()?;
    let opt_val = self
      .0
      .parse_from_string_list(&option_id.0, &default, |s| {
        member_parser
          .call((s,), None)
          .and_then(|s| Key::from_value(s.extract()?))
          .map_err(|e| e.to_string())
      })
      .map_err(exceptions::PyException::new_err)?;
    let value = opt_val
      .value
      .into_iter()
      .map(|k| k.value.consume_into_py_object(py).into_ref(py))
      .collect();
    Ok((value, format!("{:?}", opt_val.source)))
  }

  fn parse_from_string_dict<'a>(
    &self,
    py: Python,
    option_id: &'a PyOptionId,
    default: &'a PyDict,
    member_parser: &'a PyFunction,
    literal_parser: &'a PyFunction,
  ) -> PyResult<(HashMap<String, &'a PyAny>, String)> {
    let default = default
      .items()
      .into_iter()
      .map(|kv_pair| kv_pair.extract::<(String, &'a PyAny)>())
      .collect::<Result<HashMap<_, _>, _>>()?;
    let opt_val = self
      .0
      .parse_from_string_dict(
        &option_id.0,
        &default,
        |v| {
          let py_obj =
            toml_value_to_py_object(py, v).map_err(|e| format!("Could not decode toml: {e}"))?;
          member_parser
            .call((py_obj,), None)
            .map_err(|e| e.to_string())
        },
        |s| {
          literal_parser
            .call((s,), None)
            .and_then(|v| v.extract::<HashMap<String, &'a PyAny>>())
            .map_err(|e| e.to_string())
        },
      )
      .map_err(exceptions::PyException::new_err)?;
    Ok((opt_val.value, format!("{:?}", opt_val.source)))
  }
}
