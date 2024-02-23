// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::prelude::*;
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

use options::{Args, Env, Val, OptionId, OptionParser, OptionValue, Scope, ListOptionValue};

use std::collections::HashMap;
use log::warn;

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
    m.add_class::<PyOptionId>()?;
    m.add_class::<PyOptionParser>()?;
    Ok(())
}

fn val_to_py_object(py: Python, val: &Val) -> PyResult<PyObject> {
    let res = match val {
        Val::Bool(b) => b.into_py(py),
        Val::Int(i) => i.into_py(py),
        Val::Float(f) => f.into_py(py),
        Val::String(s) => s.into_py(py),
        Val::List(list) => {
            let pylist = PyList::empty(py);
            for m in list {
                pylist.append(val_to_py_object(py, m)?)?;
            }
            pylist.into_py(py)
        }
        Val::Dict(dict) => {
            let pydict = PyDict::new(py);
            for (k, v) in dict {
                pydict.set_item(k.into_py(py), val_to_py_object(py, v)?)?;
            }
            pydict.into_py(py)
        }
    };
    Ok(res)
}

pub(crate) fn py_object_to_val(obj: &PyAny) -> Result<Val, PyErr> {
    // TODO: If this is_instance_of chain shows up as significant in CPU profiles,
    //  we can use a lookup table of PyTypeObject -> conversion func instead.
    //  Alternatively, we could type-parameterize DictEdit to create a variant that contains
    //  Py* types directly,instead of Vals, for when dict-valued options are consumed by
    //  Python code, while retaining the current Val-based DictEdit for when dict-valued
    //  options are consumed in Rust code.
    //  However we don't have many dict-typed options, and even fewer with non-empty or non-tiny
    //  defaults (this function is only used to convert option default values), so it's
    //  very unlikely that this is a problem in practice.

    // NB: We check these in rough order of likelihood of the type appearing in a dict value,
    // but it is vital that we check bool before int, because bool is a subclass of int.
    if obj.is_instance_of::<PyString>() {
        return Ok(Val::String(obj.extract()?));
    } else if obj.is_instance_of::<PyBool>() {
        return Ok(Val::Bool(obj.extract()?));
    } else if obj.is_instance_of::<PyInt>() {
        return Ok(Val::Int(obj.extract()?));
    } else if obj.is_instance_of::<PyFloat>() {
        return Ok(Val::Float(obj.extract()?));
    } else if obj.is_instance_of::<PyDict>() {
        return Ok(Val::Dict(obj.downcast::<PyDict>()?.iter().map(|(k, v)| {
            Ok::<(String, Val), PyErr>((k.extract::<String>()?, py_object_to_val(v)?))
        }).collect::<Result<HashMap<_, _>,_>>()?))
    } else if obj.is_instance_of::<PyList>() || obj.is_instance_of::<PyTuple>() {
        warn!("{:?} is a list", obj);
    } else {
        return Err(PyValueError::new_err(format!(
            "Unsupported Python type in option default: {}",
            obj.get_type().name()?
        )));
    }
    Ok(Val::String("OKIDOKI".to_owned()))
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
                return Err(PyValueError::new_err(format!(
                    "Switch value should contain a single character, but was: {}",
                    s
                )))
            }
        };
        let option_id = OptionId::new(scope, components.into_iter(), switch)
            .map_err(PyValueError::new_err)?;
        Ok(Self(option_id))
    }
}

#[pyclass]
struct PyOptionParser(OptionParser);

impl PyOptionParser {
    fn get_scalar<T: ToOwned + ?Sized>(
        &self, option_id: &PyOptionId, default: &T,
        getter: fn(&OptionParser, &OptionId, &T) -> Result<OptionValue<T::Owned>, String>,) -> PyResult<T::Owned> {
        let opt_val = getter(&self.0, &option_id.0, default)
            .map_err(PyException::new_err)?;
        Ok(opt_val.value)
    }

    fn get_list<T: ToOwned + ?Sized>(
        &self, option_id: &PyOptionId, default: Vec<T::Owned>,
        getter: fn(&OptionParser, &OptionId, Vec<T::Owned>) -> Result<ListOptionValue<T::Owned>, String>,) -> PyResult<Vec<T::Owned>> {
        let opt_val = getter(&self.0, &option_id.0, default)
            .map_err(PyException::new_err)?;
        Ok(opt_val.value)
    }
}

#[pymethods]
impl PyOptionParser {
    #[new]
    #[pyo3(signature = (args, env, configs, allow_pantsrc, include_derivation))]
    fn __new__(args: Vec<String>, env: &PyDict, configs: Option<Vec<&str>>, allow_pantsrc: bool, include_derivation: bool) -> PyResult<Self> {
        let env = env
            .items()
            .into_iter()
            .map(|kv_pair| kv_pair.extract::<(String, String)>())
            .collect::<Result<HashMap<_, _>, _>>()?;

        let option_parser = OptionParser::new(Args::new(args), Env::new(env), configs, allow_pantsrc, include_derivation, None)
            .map_err(PyValueError::new_err)?;
        Ok(Self(option_parser))
    }

    fn get_bool(&self, option_id: &PyOptionId, default: bool) -> PyResult<bool> {
        self.get_scalar(option_id, &default, |op, oid, def| op.parse_bool(oid, *def))
    }

    fn get_int(&self, option_id: &PyOptionId, default: i64) -> PyResult<i64> {
        self.get_scalar(option_id, &default, |op, oid, def| op.parse_int(oid, *def))
    }

    fn get_float(&self, option_id: &PyOptionId, default: f64) -> PyResult<f64> {
        self.get_scalar(option_id, &default, |op, oid, def| op.parse_float(oid, *def))
    }

    fn get_string(&self, option_id: &PyOptionId, default: &str) -> PyResult<String> {
        self.get_scalar(option_id, default, |op, oid, def| op.parse_string(oid, def))
    }

    fn get_bool_list(
        &self,
        option_id: &PyOptionId,
        default: Vec<bool>,
    ) -> PyResult<Vec<bool>> {
        self.get_list::<bool>(option_id, default, |op, oid, def| op.parse_bool_list(oid, def))
    }

    fn get_int_list(
        &self,
        option_id: &PyOptionId,
        default: Vec<i64>,
    ) -> PyResult<Vec<i64>> {
        self.get_list::<i64>(option_id, default, |op, oid, def| op.parse_int_list(oid, def))
    }

    fn get_float_list(
        &self,
        option_id: &PyOptionId,
        default: Vec<f64>,
    ) -> PyResult<Vec<f64>> {
        self.get_list::<f64>(option_id, default, |op, oid, def| op.parse_float_list(oid, def))
    }

    fn get_string_list(
        &self,
        option_id: &PyOptionId,
        default: Vec<String>,
    ) -> PyResult<Vec<String>> {
        self.get_list::<String>(option_id, default, |op, oid, def| op.parse_string_list(oid, def))
    }

    // fn parse_from_string_list<'a>(
    //     &self,
    //     py: Python<'a>,
    //     option_id: &PyOptionId,
    //     default: Vec<&'a PyAny>,
    //     member_parser: &'a PyFunction,
    // ) -> PyResult<(Vec<&'a PyAny>, String)> {
    //     let default = default
    //         .into_iter()
    //         .map(|s| Key::from_value(s.extract()?))
    //         .collect::<Result<Vec<Key>, _>>()?;
    //     let opt_val = self
    //         .0
    //         .parse_from_string_list(&option_id.0, &default, |s| {
    //             member_parser
    //                 .call((s,), None)
    //                 .and_then(|s| Key::from_value(s.extract()?))
    //                 .map_err(|e| e.to_string())
    //         })
    //         .map_err(exceptions::PyException::new_err)?;
    //     let value = opt_val
    //         .value
    //         .into_iter()
    //         .map(|k| k.value.consume_into_py_object(py).into_ref(py))
    //         .collect();
    //     Ok((value, format!("{:?}", opt_val.source)))
    // }
    //

    fn get_dict<'a>(
        &self,
        py: Python,
        option_id: &PyOptionId,
        default: &'a PyDict,
    ) -> PyResult<HashMap<String, PyObject>> {
        warn!("DDDDD1 {:?}", default);
        let default = default.items().into_iter()
            .map(|kv_pair| {
                let (k, v) = kv_pair.extract::<(String, &'a PyAny)>()?;
                Ok::<(String, Val), PyErr>((k, py_object_to_val(v)?))
            }).collect::<Result<HashMap<_, _>, _>>()?;
        warn!("DDDDD2 {:?}", default);
        let opt_val = self.0.parse_dict(&option_id.0, default).map_err(PyException::new_err)?.value;
        opt_val.into_iter().map(|(k, v)| {
            match val_to_py_object(py, &v) {
                Ok(pyobj) => Ok((k, pyobj)),
                Err(err) => Err(err),
            }
        }).collect()
    }

    // fn parse_from_string_dict<'a>(
    //     &self,
    //     py: Python,
    //     option_id: &'a PyOptionId,
    //     default: &'a PyDict,
    //     member_parser: &'a PyFunction,
    //     literal_parser: &'a PyFunction,
    // ) -> PyResult<(HashMap<String, &'a PyAny>, String)> {
    //     let default = default
    //         .items()
    //         .into_iter()
    //         .map(|kv_pair| kv_pair.extract::<(String, &'a PyAny)>())
    //         .collect::<Result<HashMap<_, _>, _>>()?;
    //     let opt_val = self
    //         .0
    //         .parse_from_string_dict(
    //             &option_id.0,
    //             &default,
    //             |v| {
    //                 let py_obj =
    //                     toml_value_to_py_object(py, v).map_err(|e| format!("Could not decode toml: {e}"))?;
    //                 member_parser
    //                     .call((py_obj,), None)
    //                     .map_err(|e| e.to_string())
    //             },
    //             |s| {
    //                 literal_parser
    //                     .call((s,), None)
    //                     .and_then(|v| v.extract::<HashMap<String, &'a PyAny>>())
    //                     .map_err(|e| e.to_string())
    //             },
    //         )
    //         .map_err(exceptions::PyException::new_err)?;
    //     Ok((opt_val.value, format!("{:?}", opt_val.source)))
    // }
}