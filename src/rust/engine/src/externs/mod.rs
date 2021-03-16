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

use crate::core::{Failure, Key, TypeId, Value};
use crate::interning::Interns;

use cpython::{
  py_class, CompareOp, FromPyObject, ObjectProtocol, PyBool, PyBytes, PyClone, PyDict, PyErr,
  PyObject, PyResult as CPyResult, PyTuple, PyType, Python, PythonObject, ToPyObject,
};
use lazy_static::lazy_static;

use logging::PythonLogLevel;

/// Return the Python value None.
pub fn none() -> PyObject {
  let gil = Python::acquire_gil();
  gil.python().None()
}

pub fn get_type_for(val: &PyObject) -> TypeId {
  let gil = Python::acquire_gil();
  let py = gil.python();
  (&val.get_type(py)).into()
}

pub fn is_union(ty: TypeId) -> bool {
  let gil = Python::acquire_gil();
  let py = gil.python();
  let py_type = (&ty).as_py_type(py);
  let unions = py.import("pants.engine.unions").unwrap();
  unions
    .call(py, "is_union", (py_type,), None)
    .unwrap()
    .extract(py)
    .unwrap()
}

pub fn equals(h1: &PyObject, h2: &PyObject) -> bool {
  let gil = Python::acquire_gil();
  let py = gil.python();
  // NB: Although it does not precisely align with Python's definition of equality, we ban matches
  // between non-equal types to avoid legacy behavior like `assert True == 1`, which is very
  // surprising in interning, and would likely be surprising anywhere else in the engine where we
  // compare things.
  if h1.get_type(py) != h2.get_type(py) {
    return false;
  }
  h1.rich_compare(gil.python(), h2, CompareOp::Eq)
    .unwrap()
    .cast_as::<PyBool>(gil.python())
    .unwrap()
    .is_true()
}

pub fn type_for_type_id(ty: TypeId) -> PyType {
  let gil = Python::acquire_gil();
  (&ty).as_py_type(gil.python())
}

pub fn type_for(py_type: PyType) -> TypeId {
  (&py_type).into()
}

pub fn key_for(val: Value) -> Result<Key, PyErr> {
  let gil = Python::acquire_gil();
  INTERNS.key_insert(gil.python(), val)
}

pub fn val_for(key: &Key) -> Value {
  INTERNS.key_get(key)
}

pub fn store_tuple(values: Vec<Value>) -> Value {
  let gil = Python::acquire_gil();
  let arg_handles: Vec<_> = values
    .into_iter()
    .map(|v| v.consume_into_py_object(gil.python()))
    .collect();
  Value::from(PyTuple::new(gil.python(), &arg_handles).into_object())
}

/// Store a slice containing 2-tuples of (key, value) as a Python dictionary.
pub fn store_dict(keys_and_values: Vec<(Value, Value)>) -> Result<Value, PyErr> {
  let gil = Python::acquire_gil();
  let py = gil.python();
  let dict = PyDict::new(py);
  for (k, v) in keys_and_values {
    dict.set_item(
      gil.python(),
      k.consume_into_py_object(py),
      v.consume_into_py_object(py),
    )?;
  }
  Ok(Value::from(dict.into_object()))
}

///
/// Store an opaque buffer of bytes to pass to Python. This will end up as a Python `bytes`.
///
pub fn store_bytes(bytes: &[u8]) -> Value {
  let gil = Python::acquire_gil();
  Value::from(PyBytes::new(gil.python(), bytes).into_object())
}

///
/// Store an buffer of utf8 bytes to pass to Python. This will end up as a Python `unicode`.
///
pub fn store_utf8(utf8: &str) -> Value {
  let gil = Python::acquire_gil();
  Value::from(utf8.to_py_object(gil.python()).into_object())
}

pub fn store_u64(val: u64) -> Value {
  let gil = Python::acquire_gil();
  Value::from(val.to_py_object(gil.python()).into_object())
}

pub fn store_i64(val: i64) -> Value {
  let gil = Python::acquire_gil();
  Value::from(val.to_py_object(gil.python()).into_object())
}

pub fn store_bool(val: bool) -> Value {
  let gil = Python::acquire_gil();
  Value::from(val.to_py_object(gil.python()).into_object())
}

///
/// Check if a Python object has the specified field.
///
pub fn hasattr(value: &PyObject, field: &str) -> bool {
  let gil = Python::acquire_gil();
  let py = gil.python();
  value.hasattr(py, field).unwrap()
}

///
/// Gets an attribute of the given value as the given type.
///
pub fn getattr<T>(value: &PyObject, field: &str) -> Result<T, String>
where
  for<'a> T: FromPyObject<'a>,
{
  let gil = Python::acquire_gil();
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
pub fn collect_iterable(value: &PyObject) -> Result<Vec<PyObject>, String> {
  let gil = Python::acquire_gil();
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

pub fn getattr_from_frozendict(value: &PyObject, field: &str) -> BTreeMap<String, String> {
  let frozendict = getattr(value, field).unwrap();
  let pydict: PyDict = getattr(&frozendict, "_data").unwrap();
  let gil = Python::acquire_gil();
  let py = gil.python();
  pydict
    .items(py)
    .into_iter()
    .map(|(k, v)| (val_to_str(&Value::new(k)), val_to_str(&Value::new(v))))
    .collect()
}

pub fn getattr_as_string(value: &PyObject, field: &str) -> String {
  // TODO: It's possible to view a python string as a `Cow<str>`, so we could avoid actually
  // cloning in some cases.
  // TODO: We can't directly extract as a string here, because val_to_str defaults to empty string
  // for None.
  val_to_str(&getattr(value, field).unwrap())
}

pub fn key_to_str(key: &Key) -> String {
  val_to_str(&val_for(key).as_ref())
}

pub fn type_to_str(type_id: TypeId) -> String {
  getattr_as_string(&type_for_type_id(type_id).into_object(), "__name__")
}

pub fn val_to_str(obj: &PyObject) -> String {
  let gil = Python::acquire_gil();
  let py = gil.python();

  if *obj == py.None() {
    return "".to_string();
  }

  let pystring = obj.str(py).unwrap();
  pystring.to_string(py).unwrap().into_owned()
}

pub fn val_to_log_level(obj: &PyObject) -> Result<log::Level, String> {
  let res: Result<PythonLogLevel, String> = getattr(obj, "_level").and_then(|n: u64| {
    n.try_into()
      .map_err(|e: num_enum::TryFromPrimitiveError<_>| {
        format!("Could not parse {:?} as a LogLevel: {}", val_to_str(obj), e)
      })
  });
  res.map(|py_level| py_level.into())
}

pub fn create_exception(msg: &str) -> Value {
  let gil = Python::acquire_gil();
  let py = gil.python();
  Value::from(PyErr::new::<cpython::exc::Exception, _>(py, msg).instance(py))
}

pub fn check_for_python_none(value: PyObject) -> Option<PyObject> {
  let gil = Python::acquire_gil();
  let py = gil.python();
  if value == py.None() {
    return None;
  }
  Some(value)
}

pub fn call_method(value: &PyObject, method: &str, args: &[Value]) -> Result<PyObject, PyErr> {
  let arg_handles: Vec<PyObject> = args.iter().map(|v| v.clone().into()).collect();
  let gil = Python::acquire_gil();
  let args_tuple = PyTuple::new(gil.python(), &arg_handles);
  value.call_method(gil.python(), method, args_tuple, None)
}

pub fn call_function<T: AsRef<PyObject>>(func: T, args: &[Value]) -> Result<PyObject, PyErr> {
  let func: &PyObject = func.as_ref();
  let arg_handles: Vec<PyObject> = args.iter().map(|v| v.clone().into()).collect();
  let gil = Python::acquire_gil();
  let args_tuple = PyTuple::new(gil.python(), &arg_handles);
  func.call(gil.python(), args_tuple, None)
}

pub fn generator_send(generator: &Value, arg: &Value) -> Result<GeneratorResponse, Failure> {
  let gil = Python::acquire_gil();
  let py = gil.python();
  let selectors = py.import("pants.engine.internals.selectors").unwrap();
  let response = selectors
    .call(
      py,
      "native_engine_generator_send",
      (generator as &PyObject, arg as &PyObject),
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
        Ok(Get::new(py, get)?)
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

///
/// NB: Panics on failure. Only recommended for use with built-in types, such as
/// those configured in types::Types.
///
pub fn unsafe_call(type_id: TypeId, args: &[Value]) -> Value {
  let py_type = type_for_type_id(type_id);
  let arg_handles: Vec<PyObject> = args.iter().map(|v| v.clone().into()).collect();
  let gil = Python::acquire_gil();
  let args_tuple = PyTuple::new(gil.python(), &arg_handles);
  py_type
    .call(gil.python(), args_tuple, None)
    .map(Value::from)
    .unwrap_or_else(|e| {
      let gil = Python::acquire_gil();
      panic!(
        "Core type constructor `{}` failed: {:?}",
        py_type.name(gil.python()),
        e
      );
    })
}

lazy_static! {
  static ref INTERNS: Interns = Interns::new();
}

py_class!(pub class PyGeneratorResponseBreak |py| {
    data val: PyObject;
    def __new__(_cls, val: PyObject) -> CPyResult<Self> {
      Self::create_instance(py, val)
    }
});

py_class!(pub class PyGeneratorResponseGet |py| {
    data product: PyType;
    data declared_subject: PyType;
    data subject: PyObject;
    def __new__(_cls, product: PyType, declared_subject: PyType, subject: PyObject) -> CPyResult<Self> {
      Self::create_instance(py, product, declared_subject, subject)
    }
});

py_class!(pub class PyGeneratorResponseGetMulti |py| {
    data gets: PyTuple;
    def __new__(_cls, gets: PyTuple) -> CPyResult<Self> {
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
  fn new(py: Python, get: &PyGeneratorResponseGet) -> Result<Get, Failure> {
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
    write!(
      f,
      "Get({}, {})",
      type_to_str(self.output),
      key_to_str(&self.input)
    )
  }
}

pub enum GeneratorResponse {
  Break(Value),
  Get(Get),
  GetMulti(Vec<Get>),
}
