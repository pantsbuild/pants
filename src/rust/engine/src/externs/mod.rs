// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// File-specific allowances to silence internal warnings of `[pyclass]`.
#![allow(clippy::used_underscore_binding)]

use std::collections::BTreeMap;
use std::convert::TryInto;
use std::fmt;

use lazy_static::lazy_static;
use pyo3::exceptions::{PyException, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyTuple, PyType};
use pyo3::{import_exception, intern};
use pyo3::{FromPyObject, ToPyObject};

use logging::PythonLogLevel;

use crate::interning::Interns;
use crate::python::{Failure, Key, TypeId, Value};

mod address;
pub mod engine_aware;
pub mod fs;
mod interface;
#[cfg(test)]
mod interface_tests;
pub mod nailgun;
pub mod scheduler;
mod stdio;
pub mod testutil;
pub mod workunits;

pub fn register(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyFailure>()?;
    Ok(())
}

#[derive(Clone)]
#[pyclass]
pub struct PyFailure(pub Failure);

// TODO: We import this exception type because `pyo3` doesn't support declaring exceptions with
// additional fields. See https://github.com/PyO3/pyo3/issues/295
import_exception!(pants.base.exceptions, NativeEngineFailure);

pub fn equals(h1: &PyAny, h2: &PyAny) -> bool {
    // NB: Although it does not precisely align with Python's definition of equality, we ban matches
    // between non-equal types to avoid legacy behavior like `assert True == 1`, which is very
    // surprising in interning, and would likely be surprising anywhere else in the engine where we
    // compare things.
    if !h1.get_type().is(h2.get_type()) {
        return false;
    }
    h1.eq(h2).unwrap()
}

pub fn is_union(py: Python, v: &PyType) -> PyResult<bool> {
    let is_union_for_attr = intern!(py, "_is_union_for");
    if !v.hasattr(is_union_for_attr)? {
        return Ok(false);
    }

    let is_union_for = v.getattr(is_union_for_attr)?;
    Ok(is_union_for.is(v))
}

pub fn store_tuple(py: Python, values: Vec<Value>) -> Value {
    let arg_handles: Vec<_> = values
        .into_iter()
        .map(|v| v.consume_into_py_object(py))
        .collect();
    Value::from(PyTuple::new(py, &arg_handles).to_object(py))
}

/// Store a slice containing 2-tuples of (key, value) as a Python dictionary.
pub fn store_dict(py: Python, keys_and_values: Vec<(Value, Value)>) -> PyResult<Value> {
    let dict = PyDict::new(py);
    for (k, v) in keys_and_values {
        dict.set_item(k.consume_into_py_object(py), v.consume_into_py_object(py))?;
    }
    Ok(Value::from(dict.to_object(py)))
}

/// Store an opaque buffer of bytes to pass to Python. This will end up as a Python `bytes`.
pub fn store_bytes(py: Python, bytes: &[u8]) -> Value {
    Value::from(PyBytes::new(py, bytes).to_object(py))
}

/// Store a buffer of utf8 bytes to pass to Python. This will end up as a Python `str`.
pub fn store_utf8(py: Python, utf8: &str) -> Value {
    Value::from(utf8.to_object(py))
}

pub fn store_u64(py: Python, val: u64) -> Value {
    Value::from(val.to_object(py))
}

pub fn store_i64(py: Python, val: i64) -> Value {
    Value::from(val.to_object(py))
}

pub fn store_bool(py: Python, val: bool) -> Value {
    Value::from(val.to_object(py))
}

///
/// Gets an attribute of the given value as the given type.
///
pub fn getattr<'py, T>(value: &'py PyAny, field: &str) -> Result<T, String>
where
    T: FromPyObject<'py>,
{
    value
        .getattr(field)
        .map_err(|e| format!("Could not get field `{}`: {:?}", field, e))?
        .extract::<T>()
        .map_err(|e| {
            format!(
                "Field `{}` was not convertible to type {}: {:?}",
                field,
                core::any::type_name::<T>(),
                e
            )
        })
}

///
/// Collect the Values contained within an outer Python Iterable PyObject.
///
pub fn collect_iterable(value: &PyAny) -> Result<Vec<&PyAny>, String> {
    match value.iter() {
        Ok(py_iter) => py_iter
            .enumerate()
            .map(|(i, py_res)| {
                py_res.map_err(|py_err| {
                    format!(
                        "Could not iterate {}, failed to extract {}th item: {:?}",
                        val_to_str(value),
                        i,
                        py_err
                    )
                })
            })
            .collect(),
        Err(py_err) => Err(format!(
            "Could not iterate {}: {:?}",
            val_to_str(value),
            py_err
        )),
    }
}

/// Read a `FrozenDict[str, T]`.
pub fn getattr_from_str_frozendict<'p, T: FromPyObject<'p>>(
    value: &'p PyAny,
    field: &str,
) -> BTreeMap<String, T> {
    let frozendict = getattr(value, field).unwrap();
    let pydict: &PyDict = getattr(frozendict, "_data").unwrap();
    pydict
        .items()
        .into_iter()
        .map(|kv_pair| kv_pair.extract().unwrap())
        .collect()
}

pub fn getattr_as_optional_string(value: &PyAny, field: &str) -> Option<String> {
    let v = value.getattr(field).unwrap();
    if v.is_none() {
        return None;
    }
    // TODO: It's possible to view a python string as a `Cow<str>`, so we could avoid actually
    // cloning in some cases.
    Some(v.extract().unwrap())
}

/// Call the equivalent of `str()` on an arbitrary Python object.
///
/// Converts `None` to the empty string.
pub fn val_to_str(obj: &PyAny) -> String {
    if obj.is_none() {
        return "".to_string();
    }
    obj.str().unwrap().extract().unwrap()
}

pub fn val_to_log_level(obj: &PyAny) -> Result<log::Level, String> {
    let res: Result<PythonLogLevel, String> = getattr(obj, "_level").and_then(|n: u64| {
        n.try_into()
            .map_err(|e: num_enum::TryFromPrimitiveError<_>| {
                format!("Could not parse {:?} as a LogLevel: {}", val_to_str(obj), e)
            })
    });
    res.map(|py_level| py_level.into())
}

/// Link to the Pants docs using the current version of Pants.
pub fn doc_url(py: Python, slug: &str) -> String {
    let docutil_module = py.import("pants.util.docutil").unwrap();
    let doc_url_func = docutil_module.getattr("doc_url").unwrap();
    doc_url_func.call1((slug,)).unwrap().extract().unwrap()
}

pub fn create_exception(py: Python, msg: String) -> Value {
    Value::new(PyException::new_err(msg).into_py(py))
}

pub fn call_function<'py>(func: &'py PyAny, args: &[Value]) -> PyResult<&'py PyAny> {
    let args: Vec<PyObject> = args.iter().map(|v| v.clone().into()).collect();
    let args_tuple = PyTuple::new(func.py(), &args);
    func.call1(args_tuple)
}

pub fn generator_send(
    py: Python,
    generator: &Value,
    arg: &Value,
) -> Result<GeneratorResponse, Failure> {
    let selectors = py.import("pants.engine.internals.selectors").unwrap();
    let native_engine_generator_send = selectors.getattr("native_engine_generator_send").unwrap();
    let response = native_engine_generator_send
        .call1((generator.to_object(py), arg.to_object(py)))
        .map_err(|py_err| Failure::from_py_err_with_gil(py, py_err))?;

    if let Ok(b) = response.extract::<PyRef<PyGeneratorResponseBreak>>() {
        Ok(GeneratorResponse::Break(
            Value::new(b.0.clone_ref(py)),
            TypeId::new(b.0.as_ref(py).get_type()),
        ))
    } else if let Ok(get) = response.extract::<PyRef<PyGeneratorResponseGet>>() {
        Ok(GeneratorResponse::Get(Get::new(py, get)?))
    } else if let Ok(get_multi) = response.extract::<PyRef<PyGeneratorResponseGetMulti>>() {
        let gets = get_multi
            .0
            .as_ref(py)
            .iter()
            .map(|g| {
                let get = g
                    .extract::<PyRef<PyGeneratorResponseGet>>()
                    .map_err(|e| Failure::from_py_err_with_gil(py, e))?;
                Get::new(py, get)
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok(GeneratorResponse::GetMulti(gets))
    } else {
        panic!(
            "native_engine_generator_send returned unrecognized type: {:?}",
            response
        );
    }
}

/// NB: Panics on failure. Only recommended for use with built-in types, such as
/// those configured in types::Types.
pub fn unsafe_call(py: Python, type_id: TypeId, args: &[Value]) -> Value {
    let py_type = type_id.as_py_type(py);
    call_function(py_type, args)
        .map(|obj| Value::new(obj.into_py(py)))
        .unwrap_or_else(|e| {
            panic!(
                "Core type constructor `{}` failed: {:?}",
                py_type.name().unwrap(),
                e
            );
        })
}

lazy_static! {
    pub static ref INTERNS: Interns = Interns::new();
}

#[pyclass]
pub struct PyGeneratorResponseBreak(PyObject);

#[pymethods]
impl PyGeneratorResponseBreak {
    #[new]
    fn __new__(val: PyObject) -> Self {
        Self(val)
    }
}

#[pyclass(subclass)]
pub struct PyGeneratorResponseGet {
    product: Py<PyType>,
    declared_subject: Py<PyType>,
    subject: PyObject,
}

#[pymethods]
impl PyGeneratorResponseGet {
    #[new]
    fn __new__(
        py: Python,
        product: &PyAny,
        input_arg0: &PyAny,
        input_arg1: Option<&PyAny>,
    ) -> PyResult<Self> {
        let product = product.cast_as::<PyType>().map_err(|_| {
            let actual_type = product.get_type();
            PyTypeError::new_err(format!(
                "Invalid Get. The first argument (the output type) must be a type, but given \
        `{product}` with type {actual_type}."
            ))
        })?;

        let (declared_subject, subject) = if let Some(input_arg1) = input_arg1 {
            let declared_type = input_arg0.cast_as::<PyType>().map_err(|_| {
                let input_arg0_type = input_arg0.get_type();
                PyTypeError::new_err(format!(
          "Invalid Get. Because you are using the longhand form Get(OutputType, InputType, \
          input), the second argument must be a type, but given `{input_arg0}` of type \
          {input_arg0_type}."
        ))
            })?;

            if input_arg1.is_instance_of::<PyType>()? {
                return Err(PyTypeError::new_err(format!(
                    "Invalid Get. Because you are using the longhand form \
          Get(OutputType, InputType, input), the third argument should be \
          an object, rather than a type, but given {input_arg1}."
                )));
            }

            let actual_type = input_arg1.get_type();
            if !declared_type.is(actual_type) && !is_union(py, declared_type)? {
                return Err(PyTypeError::new_err(format!(
          "Invalid Get. The third argument `{input_arg1}` must have the exact same type as the \
          second argument, {declared_type}, but had the type {actual_type}."
        )));
            }

            (declared_type, input_arg1)
        } else {
            if input_arg0.is_instance_of::<PyType>()? {
                return Err(PyTypeError::new_err(format!(
                    "Invalid Get. Because you are using the shorthand form \
          Get(OutputType, InputType(constructor args)), the second argument should be \
          a constructor call, rather than a type, but given {input_arg0}."
                )));
            }

            (input_arg0.get_type(), input_arg0)
        };

        Ok(Self {
            product: product.into_py(py),
            declared_subject: declared_subject.into_py(py),
            subject: subject.into_py(py),
        })
    }

    #[getter]
    fn output_type<'p>(&'p self, py: Python<'p>) -> &'p PyType {
        self.product.as_ref(py)
    }

    #[getter]
    fn input_type<'p>(&'p self, py: Python<'p>) -> &'p PyType {
        self.declared_subject.as_ref(py)
    }

    #[getter]
    fn input<'p>(&'p self, py: Python<'p>) -> &'p PyAny {
        self.subject.as_ref(py)
    }
}

#[pyclass]
pub struct PyGeneratorResponseGetMulti(Py<PyTuple>);

#[pymethods]
impl PyGeneratorResponseGetMulti {
    #[new]
    fn __new__(gets: Py<PyTuple>) -> Self {
        Self(gets)
    }
}

#[derive(Debug)]
pub struct Get {
    pub output: TypeId,
    pub input_type: TypeId,
    pub input: Key,
}

impl Get {
    fn new(py: Python, get: PyRef<PyGeneratorResponseGet>) -> Result<Get, Failure> {
        Ok(Get {
            output: TypeId::new(get.product.as_ref(py)),
            input_type: TypeId::new(get.declared_subject.as_ref(py)),
            input: INTERNS
                .key_insert(py, get.subject.clone_ref(py))
                .map_err(|e| Failure::from_py_err_with_gil(py, e))?,
        })
    }
}

impl fmt::Display for Get {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
        write!(f, "Get({}, {})", self.output, self.input)
    }
}

pub enum GeneratorResponse {
    Break(Value, TypeId),
    Get(Get),
    GetMulti(Vec<Get>),
}
