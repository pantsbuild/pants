// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// File-specific allowances to silence internal warnings of `[pyclass]`.
#![allow(clippy::used_underscore_binding)]

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::convert::TryInto;
use std::fmt;

use lazy_static::lazy_static;
use pyo3::exceptions::{PyAssertionError, PyException, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyTuple, PyType};
use pyo3::{create_exception, import_exception, intern};
use pyo3::{FromPyObject, ToPyObject};
use smallvec::{smallvec, SmallVec};

use logging::PythonLogLevel;

use crate::interning::Interns;
use crate::python::{Failure, Key, TypeId, Value};

mod address;
mod collection;
pub mod dep_inference;
pub mod engine_aware;
pub mod fs;
mod interface;
#[cfg(test)]
mod interface_tests;
pub mod nailgun;
mod pantsd;
pub mod process;
pub mod scheduler;
mod stdio;
mod target;
pub mod testutil;
pub mod workunits;

pub fn register(py: Python, m: &PyModule) -> PyResult<()> {
  m.add_class::<PyFailure>()?;
  m.add_class::<PyGeneratorResponseBreak>()?;
  m.add_class::<PyGeneratorResponseCall>()?;
  m.add_class::<PyGeneratorResponseGet>()?;
  m.add_class::<PyGeneratorResponseGetMulti>()?;

  m.add("EngineError", py.get_type::<EngineError>())?;
  m.add("IntrinsicError", py.get_type::<IntrinsicError>())?;
  m.add(
    "IncorrectProductError",
    py.get_type::<IncorrectProductError>(),
  )?;

  Ok(())
}

create_exception!(native_engine, EngineError, PyException);
create_exception!(native_engine, IntrinsicError, EngineError);
create_exception!(native_engine, IncorrectProductError, EngineError);

#[derive(Clone)]
#[pyclass]
pub struct PyFailure(pub Failure);

#[pymethods]
impl PyFailure {
  fn get_error(&self, py: Python) -> PyErr {
    match &self.0 {
      Failure::Throw { val, .. } => val.into_py(py),
      f @ (Failure::Invalidated | Failure::MissingDigest { .. }) => {
        EngineError::new_err(format!("{f}"))
      }
    }
  }
}

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

/// Return true if the given type is a @union.
///
/// This function is also implemented in Python as `pants.engine.union.is_union`.
pub fn is_union(py: Python, v: &PyType) -> PyResult<bool> {
  let is_union_for_attr = intern!(py, "_is_union_for");
  if !v.hasattr(is_union_for_attr)? {
    return Ok(false);
  }

  let is_union_for = v.getattr(is_union_for_attr)?;
  Ok(is_union_for.is(v))
}

/// If the given type is a @union, return its in-scope types.
///
/// This function is also implemented in Python as `pants.engine.union.union_in_scope_types`.
pub fn union_in_scope_types<'p>(
  py: Python<'p>,
  v: &'p PyType,
) -> PyResult<Option<Vec<&'p PyType>>> {
  if !is_union(py, v)? {
    return Ok(None);
  }

  let union_in_scope_types: Vec<&PyType> =
    v.getattr(intern!(py, "_union_in_scope_types"))?.extract()?;
  Ok(Some(union_in_scope_types))
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
    .map_err(|e| format!("Could not get field `{field}`: {e:?}"))?
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

pub fn getattr_as_optional_string(value: &PyAny, field: &str) -> PyResult<Option<String>> {
  // TODO: It's possible to view a python string as a `Cow<str>`, so we could avoid actually
  // cloning in some cases.
  value.getattr(field)?.extract()
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
  Value::new(IntrinsicError::new_err(msg).into_py(py))
}

pub fn call_function<'py>(func: &'py PyAny, args: &[Value]) -> PyResult<&'py PyAny> {
  let args: Vec<PyObject> = args.iter().map(|v| v.clone().into()).collect();
  let args_tuple = PyTuple::new(func.py(), &args);
  func.call1(args_tuple)
}

pub fn generator_send(
  py: Python,
  generator: &Value,
  arg: Option<Value>,
  err: Option<PyErr>,
) -> Result<GeneratorResponse, Failure> {
  let selectors = py.import("pants.engine.internals.selectors").unwrap();
  let native_engine_generator_send = selectors.getattr("native_engine_generator_send").unwrap();
  let py_arg = match (arg, err) {
    (Some(arg), None) => arg.to_object(py),
    (None, Some(err)) => err.into_py(py),
    (None, None) => py.None(),
    (Some(arg), Some(err)) => {
      panic!("generator_send got both value and error: arg={arg:?}, err={err:?}")
    }
  };
  let response = native_engine_generator_send
    .call1((generator.to_object(py), py_arg))
    .map_err(|py_err| Failure::from_py_err_with_gil(py, py_err))?;

  if let Ok(b) = response.extract::<PyRef<PyGeneratorResponseBreak>>() {
    Ok(GeneratorResponse::Break(
      Value::new(b.0.clone_ref(py)),
      TypeId::new(b.0.as_ref(py).get_type()),
    ))
  } else if let Ok(call) = response.extract::<PyRef<PyGeneratorResponseCall>>() {
    // TODO: When we begin using https://github.com/pantsbuild/pants/pull/19755, this will likely
    // use a different syntax.
    Ok(GeneratorResponse::Get(call.take()?))
  } else if let Ok(get) = response.extract::<PyRef<PyGeneratorResponseGet>>() {
    Ok(GeneratorResponse::Get(get.take()?))
  } else if let Ok(get_multi) = response.extract::<PyRef<PyGeneratorResponseGetMulti>>() {
    let gets = get_multi
      .0
      .as_ref(py)
      .iter()
      .map(|gr_get| {
        let get = gr_get
          .extract::<PyRef<PyGeneratorResponseGet>>()
          .map_err(|e| Failure::from_py_err_with_gil(py, e))?
          .take()?;
        Ok::<Get, Failure>(get)
      })
      .collect::<Result<Vec<_>, _>>()?;
    Ok(GeneratorResponse::GetMulti(gets))
  } else {
    panic!("native_engine_generator_send returned unrecognized type: {response:?}");
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

/// Interprets the `Get` and `implicitly(..)` syntax, which reduces to two optional positional
/// arguments, and results in input types and inputs.
#[allow(clippy::type_complexity)]
fn interpret_get_inputs(
  py: Python,
  input_arg0: Option<&PyAny>,
  input_arg1: Option<&PyAny>,
) -> PyResult<(SmallVec<[TypeId; 2]>, SmallVec<[Key; 2]>)> {
  match (input_arg0, input_arg1) {
    (None, None) => Ok((smallvec![], smallvec![])),
    (None, Some(_)) => Err(PyAssertionError::new_err(
      "input_arg1 set, but input_arg0 was None. This should not happen with PyO3.",
    )),
    (Some(input_arg0), None) => {
      if input_arg0.is_instance_of::<PyType>() {
        return Err(PyTypeError::new_err(format!(
          "Invalid Get. Because you are using the shorthand form \
            Get(OutputType, InputType(constructor args)), the second argument should be \
            a constructor call, rather than a type, but given {input_arg0}."
        )));
      }
      if let Ok(d) = input_arg0.downcast::<PyDict>() {
        let mut input_types = SmallVec::new();
        let mut inputs = SmallVec::new();
        for (value, declared_type) in d.iter() {
          input_types.push(TypeId::new(declared_type.downcast::<PyType>().map_err(
            |_| {
              PyTypeError::new_err(
                "Invalid Get. Because the second argument was a dict, we expected the keys of the \
            dict to be the Get inputs, and the values of the dict to be the declared \
            types of those inputs.",
              )
            },
          )?));
          inputs.push(INTERNS.key_insert(py, value.into())?);
        }
        Ok((input_types, inputs))
      } else {
        Ok((
          smallvec![TypeId::new(input_arg0.get_type())],
          smallvec![INTERNS.key_insert(py, input_arg0.into())?],
        ))
      }
    }
    (Some(input_arg0), Some(input_arg1)) => {
      let declared_type = input_arg0.downcast::<PyType>().map_err(|_| {
        let input_arg0_type = input_arg0.get_type();
        PyTypeError::new_err(format!(
          "Invalid Get. Because you are using the longhand form Get(OutputType, InputType, \
          input), the second argument must be a type, but given `{input_arg0}` of type \
          {input_arg0_type}."
        ))
      })?;

      if input_arg1.is_instance_of::<PyType>() {
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

      Ok((
        smallvec![TypeId::new(declared_type)],
        smallvec![INTERNS.key_insert(py, input_arg1.into())?],
      ))
    }
  }
}

#[pyclass(subclass)]
pub struct PyGeneratorResponseCall {
  output_type: Option<TypeId>,
  input_types: SmallVec<[TypeId; 2]>,
  inputs: SmallVec<[Key; 2]>,
}

#[pymethods]
impl PyGeneratorResponseCall {
  #[new]
  fn __new__(py: Python, input_arg0: Option<&PyAny>, input_arg1: Option<&PyAny>) -> PyResult<Self> {
    let (input_types, inputs) = interpret_get_inputs(py, input_arg0, input_arg1)?;

    Ok(Self {
      output_type: None,
      input_types,
      inputs,
    })
  }

  fn set_output_type(&mut self, output_type: &PyType) {
    self.output_type = Some(TypeId::new(output_type))
  }
}

impl PyGeneratorResponseCall {
  fn take(&self) -> Result<Get, String> {
    if let Some(output_type) = self.output_type {
      Ok(Get {
        output: output_type,
        // TODO: Similar to `PyGeneratorResponseGet::take`, this should avoid these clones.
        input_types: self.input_types.clone(),
        inputs: self.inputs.clone(),
      })
    } else {
      Err("Cannot convert a Call into a Get until its output_type has been set.".to_owned())
    }
  }
}

// Contains a `RefCell<Option<Get>>` in order to allow us to `take` the content without cloning.
#[pyclass(subclass)]
pub struct PyGeneratorResponseGet(RefCell<Option<Get>>);

impl PyGeneratorResponseGet {
  fn take(&self) -> Result<Get, String> {
    self
      .0
      .borrow_mut()
      .take()
      .ok_or_else(|| "A `Get` may only be consumed once.".to_owned())
  }
}

#[pymethods]
impl PyGeneratorResponseGet {
  #[new]
  fn __new__(
    py: Python,
    product: &PyAny,
    input_arg0: Option<&PyAny>,
    input_arg1: Option<&PyAny>,
  ) -> PyResult<Self> {
    let product = product.downcast::<PyType>().map_err(|_| {
      let actual_type = product.get_type();
      PyTypeError::new_err(format!(
        "Invalid Get. The first argument (the output type) must be a type, but given \
        `{product}` with type {actual_type}."
      ))
    })?;
    let output = TypeId::new(product);

    let (input_types, inputs) = interpret_get_inputs(py, input_arg0, input_arg1)?;

    Ok(Self(RefCell::new(Some(Get {
      output,
      input_types,
      inputs,
    }))))
  }

  #[getter]
  fn output_type<'p>(&'p self, py: Python<'p>) -> PyResult<&'p PyType> {
    Ok(
      self
        .0
        .borrow()
        .as_ref()
        .ok_or_else(|| {
          PyException::new_err(
            "A `Get` may not be consumed after being provided to the @rule engine.",
          )
        })?
        .output
        .as_py_type(py),
    )
  }

  #[getter]
  fn input_types<'p>(&'p self, py: Python<'p>) -> PyResult<Vec<&'p PyType>> {
    Ok(
      self
        .0
        .borrow()
        .as_ref()
        .ok_or_else(|| {
          PyException::new_err(
            "A `Get` may not be consumed after being provided to the @rule engine.",
          )
        })?
        .input_types
        .iter()
        .map(|t| t.as_py_type(py))
        .collect(),
    )
  }

  #[getter]
  fn inputs(&self) -> PyResult<Vec<PyObject>> {
    Ok(
      self
        .0
        .borrow()
        .as_ref()
        .ok_or_else(|| {
          PyException::new_err(
            "A `Get` may not be consumed after being provided to the @rule engine.",
          )
        })?
        .inputs
        .iter()
        .map(|k| {
          let pyo: PyObject = k.value.clone().into();
          pyo
        })
        .collect(),
    )
  }

  fn __repr__(&self) -> PyResult<String> {
    Ok(format!(
      "{}",
      self.0.borrow().as_ref().ok_or_else(|| {
        PyException::new_err(
          "A `Get` may not be consumed after being provided to the @rule engine.",
        )
      })?
    ))
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
  pub input_types: SmallVec<[TypeId; 2]>,
  pub inputs: SmallVec<[Key; 2]>,
}

impl fmt::Display for Get {
  fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
    write!(f, "Get({}", self.output)?;
    match self.input_types.len() {
      0 => write!(f, ")"),
      1 => write!(f, ", {}, {})", self.input_types[0], self.inputs[0]),
      _ => write!(
        f,
        ", {{{}}})",
        self
          .input_types
          .iter()
          .zip(self.inputs.iter())
          .map(|(t, k)| { format!("{k}: {t}") })
          .collect::<Vec<_>>()
          .join(", ")
      ),
    }
  }
}

pub enum GeneratorResponse {
  Break(Value, TypeId),
  Get(Get),
  GetMulti(Vec<Get>),
}
