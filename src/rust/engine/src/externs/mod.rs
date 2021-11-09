// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// File-specific allowances to silence internal warnings of `py_class!`.
#![allow(
  clippy::used_underscore_binding,
  clippy::transmute_ptr_to_ptr,
  clippy::zero_ptr
)]

pub mod engine_aware;
pub mod fs;
mod interface;
#[cfg(test)]
mod interface_tests;
mod stdio;

use std::collections::BTreeMap;
use std::convert::AsRef;
use std::convert::TryInto;
use std::fmt;

use crate::interning::Interns;
use crate::python::{Failure, Key, TypeId, Value};

use cpython::{ObjectProtocol, PyClone};
use lazy_static::lazy_static;
use pyo3::basic::CompareOp;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyTuple};
use pyo3::ToPyObject;

use logging::PythonLogLevel;

pub fn equals(h1: &PyAny, h2: &PyAny) -> bool {
  // NB: Although it does not precisely align with Python's definition of equality, we ban matches
  // between non-equal types to avoid legacy behavior like `assert True == 1`, which is very
  // surprising in interning, and would likely be surprising anywhere else in the engine where we
  // compare things.
  if h1.get_type() != h2.get_type() {
    return false;
  }
  h1.rich_compare(h2, CompareOp::Eq)
    .unwrap()
    .cast_as::<PyBool>()
    .unwrap()
    .is_true()
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
pub fn getattr<T>(value: &cpython::PyObject, field: &str) -> Result<T, String>
where
  for<'a> T: cpython::FromPyObject<'a>,
{
  let gil = cpython::Python::acquire_gil();
  let py = gil.python();
  value
    .getattr(py, field)
    .map_err(|e| format!("Could not get field `{}`: {:?}", field, e))?
    .extract::<T>(py)
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
pub fn collect_iterable(value: &cpython::PyObject) -> Result<Vec<cpython::PyObject>, String> {
  let gil = cpython::Python::acquire_gil();
  let py = gil.python();
  match value.iter(py) {
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

/// Read a `FrozenDict[str, str]`.
pub fn getattr_from_str_frozendict(value: &cpython::PyObject, field: &str) -> BTreeMap<String, String> {
  let frozendict = getattr(value, field).unwrap();
  let pydict: cpython::PyDict = getattr(&frozendict, "_data").unwrap();
  let gil = cpython::Python::acquire_gil();
  let py = gil.python();
  pydict
    .items(py)
    .into_iter()
    .map(|(k, v)| (k.extract(py).unwrap(), v.extract(py).unwrap()))
    .collect()
}

pub fn getattr_as_optional_string(
  py: cpython::Python,
  value: &cpython::PyObject,
  field: &str,
) -> Option<String> {
  let v = value.getattr(py, field).unwrap();
  if v.is_none(py) {
    return None;
  }
  // TODO: It's possible to view a python string as a `Cow<str>`, so we could avoid actually
  // cloning in some cases.
  Some(v.extract(py).unwrap())
}

/// Call the equivalent of `str()` on an arbitrary Python object.
///
/// Converts `None` to the empty string.
pub fn val_to_str(obj: &cpython::PyObject) -> String {
  let gil = cpython::Python::acquire_gil();
  let py = gil.python();

  if *obj == py.None() {
    return "".to_string();
  }

  let pystring = obj.str(py).unwrap();
  pystring.to_string(py).unwrap().into_owned()
}

pub fn val_to_log_level(obj: &cpython::PyObject) -> Result<log::Level, String> {
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

pub fn create_exception(py: cpython::Python, msg: &str) -> Value {
  Value::from(cpython::PyErr::new::<cpython::exc::Exception, _>(py, msg).instance(py))
}

pub fn call_method0(
  py: cpython::Python,
  value: &cpython::PyObject,
  method: &str,
) -> Result<cpython::PyObject, cpython::PyErr> {
  value.call_method(py, method, cpython::PyTuple::new(py, &[]), None)
}

pub fn call_function<T: AsRef<cpython::PyObject>>(
  func: T,
  args: &[Value],
) -> Result<cpython::PyObject, cpython::PyErr> {
  let func: &cpython::PyObject = func.as_ref();
  let arg_handles: Vec<cpython::PyObject> = args.iter().map(|v| v.clone().into()).collect();
  let gil = cpython::Python::acquire_gil();
  let args_tuple = cpython::PyTuple::new(gil.python(), &arg_handles);
  func.call(gil.python(), args_tuple, None)
}

pub fn generator_send(generator: &Value, arg: &Value) -> Result<GeneratorResponse, Failure> {
  let gil = cpython::Python::acquire_gil();
  let py = gil.python();
  let selectors = py.import("pants.engine.internals.selectors").unwrap();
  let response = selectors
    .call(
      py,
      "native_engine_generator_send",
      (generator as &cpython::PyObject, arg as &cpython::PyObject),
      None,
    )
    .map_err(|py_err| Failure::from_py_err_with_gil(py, py_err))?;

  if let Ok(b) = response.cast_as::<PyGeneratorResponseBreak>(py) {
    Ok(GeneratorResponse::Break(Value::new(
      b.val(py).clone_ref(py),
    )))
  } else if let Ok(get) = response.cast_as::<PyGeneratorResponseGet>(py) {
    Ok(GeneratorResponse::Get(Get::new(py, get)?))
  } else if let Ok(get_multi) = response.cast_as::<PyGeneratorResponseGetMulti>(py) {
    let gets = get_multi
      .gets(py)
      .iter(py)
      .map(|g| {
        let get = g
          .cast_as::<PyGeneratorResponseGet>(py)
          .map_err(|e| Failure::from_py_err_with_gil(py, e.into()))?;
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
  let arg_handles: Vec<cpython::PyObject> = args.iter().map(|v| v.clone().into()).collect();
  let args_tuple = PyTuple::new(py, &arg_handles);
  py_type
    .call(args_tuple, None)
    .map(Value::from)
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

cpython::py_class!(pub class PyGeneratorResponseBreak |py| {
    data val: cpython::PyObject;
    def __new__(_cls, val: cpython::PyObject) -> cpython::PyResult<Self> {
      Self::create_instance(py, val)
    }
});

cpython::py_class!(pub class PyGeneratorResponseGet |py| {
    data product: cpython::PyType;
    data declared_subject: cpython::PyType;
    data subject: cpython::PyObject;
    def __new__(_cls, product: cpython::PyType, declared_subject: cpython::PyType, subject: cpython::PyObject) -> cpython::PyResult<Self> {
      Self::create_instance(py, product, declared_subject, subject)
    }
});

cpython::py_class!(pub class PyGeneratorResponseGetMulti |py| {
    data gets: cpython::PyTuple;
    def __new__(_cls, gets: cpython::PyTuple) -> cpython::PyResult<Self> {
      Self::create_instance(py, gets)
    }
});

#[derive(Debug)]
pub struct Get {
  pub output: TypeId,
  pub input: Key,
  pub input_type: TypeId,
}

impl Get {
  fn new(py: cpython::Python, get: &PyGeneratorResponseGet) -> Result<Get, Failure> {
    Ok(Get {
      output: get.product(py).into(),
      input: INTERNS
        .key_insert(py, get.subject(py).clone_ref(py).into())
        .map_err(|e| Failure::from_py_err_with_gil(py, e))?,
      input_type: get.declared_subject(py).into(),
    })
  }
}

impl fmt::Display for Get {
  fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
    write!(f, "Get({}, {})", self.output, self.input)
  }
}

pub enum GeneratorResponse {
  Break(Value),
  Get(Get),
  GetMulti(Vec<Get>),
}
