// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::exceptions::{PyException, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

use options::{Args, DictOptionValue, Env, ListOptionValue, OptionId, OptionParser, OptionalOptionValue, Scope, Val};

use std::collections::HashMap;

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
    m.add_class::<PyOptionId>()?;
    m.add_class::<PyBoolOptionValue>()?;
    m.add_class::<PyIntOptionValue>()?;
    m.add_class::<PyFloatOptionValue>()?;
    m.add_class::<PyStrOptionValue>()?;
    m.add_class::<PyBoolListOptionValue>()?;
    m.add_class::<PyIntListOptionValue>()?;
    m.add_class::<PyFloatListOptionValue>()?;
    m.add_class::<PyStrListOptionValue>()?;
    m.add_class::<PyDictOptionValue>()?;
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
        Ok(Val::String(obj.extract()?))
    } else if obj.is_instance_of::<PyBool>() {
        Ok(Val::Bool(obj.extract()?))
    } else if obj.is_instance_of::<PyInt>() {
        Ok(Val::Int(obj.extract()?))
    } else if obj.is_instance_of::<PyFloat>() {
        Ok(Val::Float(obj.extract()?))
    } else if obj.is_instance_of::<PyDict>() {
        Ok(Val::Dict(
            obj.downcast::<PyDict>()?
                .iter()
                .map(|(k, v)| {
                    Ok::<(String, Val), PyErr>((k.extract::<String>()?, py_object_to_val(v)?))
                })
                .collect::<Result<HashMap<_, _>, _>>()?,
        ))
    } else if obj.is_instance_of::<PyList>() {
        Ok(Val::List(
            obj.downcast::<PyList>()?
                .iter()
                .map(py_object_to_val)
                .collect::<Result<Vec<_>, _>>()?,
        ))
    } else if obj.is_instance_of::<PyTuple>() {
        Ok(Val::List(
            obj.downcast::<PyTuple>()?
                .iter()
                .map(py_object_to_val)
                .collect::<Result<Vec<_>, _>>()?,
        ))
    } else {
        Err(PyValueError::new_err(format!(
            "Unsupported Python type in option default: {}",
            obj.get_type().name()?
        )))
    }
}

#[pyclass]
struct PyOptionId(OptionId);

#[pyclass]
struct PyBoolOptionValue(OptionalOptionValue<bool>);

#[pyclass]
struct PyIntOptionValue(OptionalOptionValue<i64>);

#[pyclass]
struct PyFloatOptionValue(OptionalOptionValue<f64>);

#[pyclass]
struct PyStrOptionValue(OptionalOptionValue<String>);

#[pyclass]
struct PyBoolListOptionValue(ListOptionValue<bool>);

#[pyclass]
struct PyIntListOptionValue(ListOptionValue<i64>);

#[pyclass]
struct PyFloatListOptionValue(ListOptionValue<f64>);

#[pyclass]
struct PyStrListOptionValue(ListOptionValue<String>);

#[pyclass]
struct PyDictOptionValue(DictOptionValue);

#[pymethods]
impl PyOptionId {
    #[new]
    #[pyo3(signature = (*components, scope = None, switch = None))]
    fn __new__(components: &PyTuple, scope: Option<&str>, switch: Option<&str>) -> PyResult<Self> {
        let components = components
            .iter()
            .map(|c| c.extract::<String>())
            .collect::<Result<Vec<_>, _>>()?;
        let scope = scope.map(Scope::named).unwrap_or(Scope::Global);
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
        let option_id =
            OptionId::new(scope, components.into_iter(), switch).map_err(PyValueError::new_err)?;
        Ok(Self(option_id))
    }
}

#[pyclass]
struct PyOptionParser(OptionParser);

#[allow(clippy::type_complexity)]
impl PyOptionParser {
    fn get_list<T: ToOwned + ?Sized>(
        &self,
        option_id: &PyOptionId,
        default: Vec<T::Owned>,
        getter: fn(
            &OptionParser,
            &OptionId,
            Vec<T::Owned>,
        ) -> Result<ListOptionValue<T::Owned>, String>,
    ) -> PyResult<ListOptionValue<T::Owned>> {
        let opt_val = getter(&self.0, &option_id.0, default).map_err(PyException::new_err)?;
        Ok(opt_val)
    }
}

#[pymethods]
impl PyOptionParser {
    #[new]
    #[pyo3(signature = (args, env, configs, allow_pantsrc, include_derivation))]
    fn __new__(
        args: Vec<String>,
        env: &PyDict,
        configs: Option<Vec<&str>>,
        allow_pantsrc: bool,
        include_derivation: bool,
    ) -> PyResult<Self> {
        let env = env
            .items()
            .into_iter()
            .map(|kv_pair| kv_pair.extract::<(String, String)>())
            .collect::<Result<HashMap<_, _>, _>>()?;

        let option_parser = OptionParser::new(
            Args::new(args),
            Env::new(env),
            configs,
            allow_pantsrc,
            include_derivation,
            None,
        )
        .map_err(PyValueError::new_err)?;
        Ok(Self(option_parser))
    }

    fn get_bool(&self, option_id: &PyOptionId, default: Option<bool>) -> PyResult<PyBoolOptionValue> {
        Ok(self.0.parse_bool_optional(&option_id.0, default).map(PyBoolOptionValue).map_err(PyException::new_err)?)
    }

    fn get_int(&self, option_id: &PyOptionId, default: Option<i64>) -> PyResult<PyIntOptionValue> {
        Ok(self.0.parse_int_optional(&option_id.0, default).map(PyIntOptionValue).map_err(PyException::new_err)?)
    }

    fn get_float(&self, option_id: &PyOptionId, default: Option<f64>) -> PyResult<PyFloatOptionValue> {
        Ok(self.0.parse_float_optional(&option_id.0, default).map(PyFloatOptionValue).map_err(PyException::new_err)?)
    }

    fn get_string(&self, option_id: &PyOptionId, default: Option<&str>) -> PyResult<PyStrOptionValue> {
        Ok(self.0.parse_string_optional(&option_id.0, default).map(PyStrOptionValue).map_err(PyException::new_err)?)
    }

    fn get_bool_list(&self, option_id: &PyOptionId, default: Vec<bool>) -> PyResult<PyBoolListOptionValue> {
        self.get_list::<bool>(option_id, default, |op, oid, def| {
            op.parse_bool_list(oid, def)
        }).map(PyBoolListOptionValue)
    }

    fn get_int_list(&self, option_id: &PyOptionId, default: Vec<i64>) -> PyResult<PyIntListOptionValue> {
        self.get_list::<i64>(option_id, default, |op, oid, def| {
            op.parse_int_list(oid, def)
        }).map(PyIntListOptionValue)
    }

    fn get_float_list(&self, option_id: &PyOptionId, default: Vec<f64>) -> PyResult<PyFloatListOptionValue> {
        self.get_list::<f64>(option_id, default, |op, oid, def| {
            op.parse_float_list(oid, def)
        }).map(PyFloatListOptionValue)
    }

    fn get_string_list(
        &self,
        option_id: &PyOptionId,
        default: Vec<String>,
    ) -> PyResult<PyStrListOptionValue> {
        self.get_list::<String>(option_id, default, |op, oid, def| {
            op.parse_string_list(oid, def)
        }).map(PyStrListOptionValue)
    }

    fn get_dict(
        &self,
        py: Python,
        option_id: &PyOptionId,
        default: &PyDict,
    ) -> PyResult<HashMap<String, PyObject>> {
        let default = default
            .items()
            .into_iter()
            .map(|kv_pair| {
                let (k, v) = kv_pair.extract::<(String, &PyAny)>()?;
                Ok::<(String, Val), PyErr>((k, py_object_to_val(v)?))
            })
            .collect::<Result<HashMap<_, _>, _>>()?;
        let opt_val = self
            .0
            .parse_dict(&option_id.0, default)
            .map_err(PyException::new_err)?
            .value;
        opt_val
            .into_iter()
            .map(|(k, v)| match val_to_py_object(py, &v) {
                Ok(pyobj) => Ok((k, pyobj)),
                Err(err) => Err(err),
            })
            .collect()
    }
}
