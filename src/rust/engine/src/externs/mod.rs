// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// File-specific allowances to silence internal warnings of `py_class!`.
#![allow(
  clippy::used_underscore_binding,
  clippy::transmute_ptr_to_ptr,
  clippy::zero_ptr
)]

mod interface;
#[cfg(test)]
mod interface_tests;

use std::collections::BTreeMap;
use std::fmt;
use std::sync::atomic;

use crate::core::{Failure, Function, Key, TypeId, Value};
use crate::interning::Interns;

use cpython::{
  py_class, CompareOp, FromPyObject, ObjectProtocol, PyBool, PyBytes, PyClone, PyDict, PyErr,
  PyObject, PyResult as CPyResult, PyString, PyTuple, PyType, Python, PythonObject, ToPyObject,
};
use itertools::Itertools;
use lazy_static::lazy_static;
use parking_lot::RwLock;

/// Return the Python value None.
pub fn none() -> PyObject {
  let gil = Python::acquire_gil();
  gil.python().None()
}

pub fn get_value_from_type_id(ty: TypeId) -> Value {
  with_interns(|interns| {
    let gil = Python::acquire_gil();
    let py = gil.python();
    Value::from(interns.type_get(&ty).clone_ref(py).into_object())
  })
}

pub fn get_type_for(val: &Value) -> TypeId {
  with_interns_mut(|interns| {
    let gil = Python::acquire_gil();
    let py = gil.python();
    let py_type = val.get_type(py);
    interns.type_insert(py, py_type)
  })
}

pub fn is_union(ty: TypeId) -> bool {
  with_interns(|interns| {
    with_externs(|py, e| {
      let py_type = interns.type_get(&ty);
      e.call_method(py, "is_union", (py_type,), None)
        .unwrap()
        .cast_as::<PyBool>(py)
        .unwrap()
        .is_true()
    })
  })
}

pub fn equals(h1: &PyObject, h2: &PyObject) -> bool {
  let gil = Python::acquire_gil();
  h1.rich_compare(gil.python(), h2, CompareOp::Eq)
    .unwrap()
    .cast_as::<PyBool>(gil.python())
    .unwrap()
    .is_true()
}

pub fn type_for(py_type: PyType) -> TypeId {
  with_interns_mut(|interns| {
    let gil = Python::acquire_gil();
    interns.type_insert(gil.python(), py_type)
  })
}

pub fn acquire_key_for(val: Value) -> Result<Key, Failure> {
  key_for(val).map_err(|e| {
    let gil = Python::acquire_gil();
    let py = gil.python();
    Failure::from_py_err(py, e)
  })
}

pub fn key_for(val: Value) -> Result<Key, PyErr> {
  with_interns_mut(|interns| {
    let gil = Python::acquire_gil();
    interns.key_insert(gil.python(), val)
  })
}

pub fn val_for(key: &Key) -> Value {
  with_interns(|interns| interns.key_get(key).clone())
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
/// Gets an attribute of the given value as the given type.
///
pub fn getattr<T>(value: &Value, field: &str) -> Result<T, String>
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
/// Pulls out the value specified by the field name from a given Value
///
pub fn project_ignoring_type(value: &Value, field: &str) -> Value {
  getattr(value, field).unwrap()
}

pub fn project_multi(value: &Value, field: &str) -> Vec<Value> {
  getattr(value, field).unwrap()
}

pub fn project_bool(value: &Value, field: &str) -> bool {
  getattr(value, field).unwrap()
}

pub fn project_multi_strs(value: &Value, field: &str) -> Vec<String> {
  getattr(value, field).unwrap()
}

// This is intended for projecting environment variable maps - i.e. Python Dict[str, str] that are
// encoded as a Tuple of an (even) number of str's. It could be made more general if we need
// similar functionality for something else.
pub fn project_tuple_encoded_map(
  value: &Value,
  field: &str,
) -> Result<BTreeMap<String, String>, String> {
  let parts = project_multi_strs(&value, field);
  if parts.len() % 2 != 0 {
    return Err("Error parsing env: odd number of parts".to_owned());
  }
  Ok(parts.into_iter().tuples::<(_, _)>().collect())
}

pub fn project_str(value: &Value, field: &str) -> String {
  // TODO: It's possible to view a python string as a `Cow<str>`, so we could avoid actually
  // cloning in some cases.
  // TODO: We can't directly extract as a string here, because val_to_str defaults to empty string
  // for None.
  val_to_str(&getattr(value, field).unwrap())
}

pub fn project_u64(value: &Value, field: &str) -> u64 {
  getattr(value, field).unwrap()
}

pub fn project_maybe_u64(value: &Value, field: &str) -> Result<u64, String> {
  getattr(value, field)
}

pub fn project_f64(value: &Value, field: &str) -> f64 {
  getattr(value, field).unwrap()
}

pub fn project_bytes(value: &Value, field: &str) -> Vec<u8> {
  // TODO: It's possible to view a python bytes as a `&[u8]`, so we could avoid actually
  // cloning in some cases.
  getattr(value, field).unwrap()
}

pub fn key_to_str(key: &Key) -> String {
  val_to_str(&val_for(key))
}

pub fn type_to_str(type_id: TypeId) -> String {
  project_str(&get_value_from_type_id(type_id), "__name__")
}

pub fn val_to_str(val: &Value) -> String {
  // TODO: to_string(py) returns a Cow<str>, so we could avoid actually cloning in some cases.
  with_externs(|py, e| {
    e.call_method(py, "val_to_str", (val as &PyObject,), None)
      .unwrap()
      .cast_as::<PyString>(py)
      .unwrap()
      .to_string(py)
      .map(|cow| cow.into_owned())
      .unwrap()
  })
}

pub fn create_exception(msg: &str) -> Value {
  Value::from(with_externs(|py, e| e.call_method(py, "create_exception", (msg,), None)).unwrap())
}

pub fn call_method(value: &Value, method: &str, args: &[Value]) -> Result<Value, Failure> {
  let arg_handles: Vec<PyObject> = args.iter().map(|v| v.clone().into()).collect();
  let gil = Python::acquire_gil();
  let args_tuple = PyTuple::new(gil.python(), &arg_handles);
  value
    .call_method(gil.python(), method, args_tuple, None)
    .map(Value::from)
    .map_err(|py_err| Failure::from_py_err(gil.python(), py_err))
}

pub fn call(func: &Value, args: &[Value]) -> Result<Value, Failure> {
  let arg_handles: Vec<PyObject> = args.iter().map(|v| v.clone().into()).collect();
  let gil = Python::acquire_gil();
  let args_tuple = PyTuple::new(gil.python(), &arg_handles);
  func
    .call(gil.python(), args_tuple, None)
    .map(Value::from)
    .map_err(|py_err| Failure::from_py_err(gil.python(), py_err))
}

pub fn generator_send(generator: &Value, arg: &Value) -> Result<GeneratorResponse, Failure> {
  let response = with_externs(|py, e| {
    e.call_method(
      py,
      "generator_send",
      (generator as &PyObject, arg as &PyObject),
      None,
    )
    .map_err(|py_err| Failure::from_py_err(py, py_err))
  })?;

  let gil = Python::acquire_gil();
  let py = gil.python();
  if let Ok(b) = response.cast_as::<PyGeneratorResponseBreak>(py) {
    Ok(GeneratorResponse::Break(Value::new(
      b.val(py).clone_ref(py),
    )))
  } else if let Ok(get) = response.cast_as::<PyGeneratorResponseGet>(py) {
    with_interns_mut(|interns| {
      let gil = Python::acquire_gil();
      Ok(GeneratorResponse::Get(Get::new(
        gil.python(),
        interns,
        get,
      )?))
    })
  } else if let Ok(get_multi) = response.cast_as::<PyGeneratorResponseGetMulti>(py) {
    with_interns_mut(|interns| {
      let gil = Python::acquire_gil();
      let py = gil.python();
      let gets = get_multi
        .gets(py)
        .iter(py)
        .map(|g| {
          let get = g
            .cast_as::<PyGeneratorResponseGet>(py)
            .map_err(|e| Failure::from_py_err(py, e.into()))?;
          Ok(Get::new(py, interns, get)?)
        })
        .collect::<Result<Vec<_>, _>>()?;
      Ok(GeneratorResponse::GetMulti(gets))
    })
  } else {
    panic!("generator_send returned unrecognized type: {:?}", response);
  }
}

///
/// NB: Panics on failure. Only recommended for use with built-in functions, such as
/// those configured in types::Types.
///
pub fn unsafe_call(func: &Function, args: &[Value]) -> Value {
  let func_val = with_interns(|interns| interns.key_get(&func.0).clone());
  call(&func_val, args).unwrap_or_else(|e| {
    panic!("Core function `{}` failed: {:?}", val_to_str(&func_val), e);
  })
}

lazy_static! {
  // See set_externs.
  static ref EXTERNS: atomic::AtomicPtr<PyObject> = atomic::AtomicPtr::new(Box::into_raw(Box::new(none())));

  // Strangely enough, GILProtected does not actually provide mutual exclusion, so we use a RwLock
  // here. To avoid deadlocks, the `with_interns` and `with_interns_mut` accessors acquire the GIL
  // and then explicitly release it before acquiring this lock. That way we can guarantee that this
  // lock is always acquired before the GIL.
  //   see https://github.com/dgrunwald/rust-cpython/issues/218
  static ref INTERNS: RwLock<Interns> = RwLock::new(Interns::new());
}

///
/// Set the static Externs for this process. All other methods of this module will fail
/// until this has been called.
///
pub fn set_externs(externs: PyObject) {
  EXTERNS.store(Box::into_raw(Box::new(externs)), atomic::Ordering::Relaxed);
}

fn with_externs<F, T>(f: F) -> T
where
  F: FnOnce(Python, &PyObject) -> T,
{
  let gil = Python::acquire_gil();
  let externs = unsafe { Box::from_raw(EXTERNS.load(atomic::Ordering::Relaxed)) };
  let result = f(gil.python(), &externs);
  std::mem::forget(externs);
  result
}

fn with_interns<F, T>(f: F) -> T
where
  F: Send + FnOnce(&Interns) -> T,
{
  let gil = Python::acquire_gil();
  gil.python().allow_threads(|| {
    let interns = INTERNS.read();
    f(&interns)
  })
}

fn with_interns_mut<F, T>(f: F) -> T
where
  F: Send + FnOnce(&mut Interns) -> T,
{
  let gil = Python::acquire_gil();
  gil.python().allow_threads(|| {
    let mut interns = INTERNS.write();
    f(&mut interns)
  })
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
  pub product: TypeId,
  pub subject: Key,
  pub declared_subject: Option<TypeId>,
}

impl Get {
  fn new(py: Python, interns: &mut Interns, get: &PyGeneratorResponseGet) -> Result<Get, Failure> {
    Ok(Get {
      product: interns.type_insert(py, get.product(py).clone_ref(py)),
      subject: interns
        .key_insert(py, get.subject(py).clone_ref(py).into())
        .map_err(|e| Failure::from_py_err(py, e))?,
      declared_subject: Some(interns.type_insert(py, get.declared_subject(py).clone_ref(py))),
    })
  }
}

impl fmt::Display for Get {
  fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
    write!(
      f,
      "Get({}, {})",
      type_to_str(self.product),
      key_to_str(&self.subject)
    )
  }
}

pub enum GeneratorResponse {
  Break(Value),
  Get(Get),
  GetMulti(Vec<Get>),
}
