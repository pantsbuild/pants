// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// File-specific allowances to silence internal warnings of `[pyclass]`.
#![allow(clippy::used_underscore_binding)]

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::convert::TryInto;
use std::fmt;

use lazy_static::lazy_static;
use pyo3::exceptions::{PyAssertionError, PyException, PyStopIteration, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PySequence, PyTuple, PyType};
use pyo3::{create_exception, import_exception, intern};
use pyo3::{FromPyObject, ToPyObject};
use smallvec::{smallvec, SmallVec};

use logging::PythonLogLevel;
use rule_graph::RuleId;

use crate::interning::Interns;
use crate::python::{Failure, Key, TypeId, Value};

mod address;
pub mod dep_inference;
pub mod engine_aware;
pub mod fs;
mod interface;
#[cfg(test)]
mod interface_tests;
pub mod nailgun;
mod options;
mod pantsd;
pub mod process;
pub mod scheduler;
mod stdio;
mod target;
pub mod testutil;
pub mod workunits;

pub fn register(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyFailure>()?;
    m.add_class::<PyGeneratorResponseCall>()?;
    m.add_class::<PyGeneratorResponseGet>()?;

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
            Failure::Throw { val, .. } => PyErr::from_value(val.as_ref().as_ref(py)),
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

pub(crate) enum GeneratorInput {
    Initial,
    Arg(Value),
    Err(PyErr),
}

///
/// A specification for how the native engine interacts with @rule coroutines:
/// - coroutines may await:
///   - `Get`/`Effect`/`Call`,
///   - other coroutines,
///   - sequences of those types.
/// - we will `send` back a single value or tupled values to the coroutine, or `throw` an exception.
/// - a coroutine will eventually return a single return value.
///
pub(crate) fn generator_send(
    py: Python,
    generator_type: &TypeId,
    generator: &Value,
    input: GeneratorInput,
) -> Result<GeneratorResponse, Failure> {
    let (response_unhandled, maybe_thrown) = match input {
        GeneratorInput::Arg(arg) => {
            let response = generator
                .getattr(py, intern!(py, "send"))?
                .call1(py, (&*arg,));
            (response, None)
        }
        GeneratorInput::Err(err) => {
            let throw_method = generator.getattr(py, intern!(py, "throw"))?;
            if err.is_instance_of::<NativeEngineFailure>(py) {
                let throw = err
                    .value(py)
                    .getattr(intern!(py, "failure"))?
                    .extract::<PyRef<PyFailure>>()?
                    .get_error(py);
                let response = throw_method.call1(py, (&throw,));
                (response, Some((throw, err)))
            } else {
                let response = throw_method.call1(py, (err,));
                (response, None)
            }
        }
        GeneratorInput::Initial => {
            let response = generator
                .getattr(py, intern!(py, "send"))?
                .call1(py, (&py.None(),));
            (response, None)
        }
    };

    let response = match response_unhandled {
        Err(e) if e.is_instance_of::<PyStopIteration>(py) => {
            let value = e.into_value(py).getattr(py, intern!(py, "value"))?;
            let type_id = TypeId::new(value.as_ref(py).get_type());
            return Ok(GeneratorResponse::Break(Value::new(value), type_id));
        }
        Err(e) => {
            match (maybe_thrown, e.cause(py)) {
                (Some((thrown, err)), Some(cause)) if thrown.value(py).is(cause.value(py)) => {
                    // Preserve the engine traceback by using the wrapped failure error as cause. The cause
                    // will be swapped back again in `Failure::from_py_err_with_gil()` to preserve the python
                    // traceback.
                    e.set_cause(py, Some(err));
                }
                _ => (),
            };
            return Err(e.into());
        }
        Ok(r) => r,
    };

    let result = if let Ok(call) = response.extract::<PyRef<PyGeneratorResponseCall>>(py) {
        Ok(GeneratorResponse::Call(call.take()?))
    } else if let Ok(get) = response.extract::<PyRef<PyGeneratorResponseGet>>(py) {
        // It isn't necessary to differentiate between `Get` and `Effect` here, as the static
        // analysis of `@rule`s has already validated usage.
        Ok(GeneratorResponse::Get(get.take()?))
    } else if let Ok(get_multi) = response.downcast::<PySequence>(py) {
        // Was an `All` or `MultiGet`.
        let gogs = get_multi
            .iter()?
            .map(|gog| {
                let gog = gog?;
                // TODO: Find a better way to check whether something is a coroutine... this seems
                // unnecessarily awkward.
                if gog.is_instance(generator_type.as_py_type(py).into())? {
                    Ok(GetOrGenerator::Generator(Value::new(gog.into())))
                } else if let Ok(get) = gog.extract::<PyRef<PyGeneratorResponseGet>>() {
                    Ok(GetOrGenerator::Get(
                        get.take().map_err(PyException::new_err)?,
                    ))
                } else {
                    Err(PyValueError::new_err(format!(
            "Expected an `All` or `MultiGet` to receive either `Get`s or calls to rules, \
            but got: {response}"
          )))
                }
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok(GeneratorResponse::All(gogs))
    } else {
        Err(PyValueError::new_err(format!(
      "Async @rule error. Expected a rule query such as `Get(..)` or similar, but got: {response}"
    )))
    };

    Ok(result?)
}

/// NB: Panics on failure. Only recommended for use with built-in types, such as
/// those configured in types::Types.
pub fn unsafe_call(py: Python, type_id: TypeId, args: &[Value]) -> Value {
    let py_type = type_id.as_py_type(py);
    let args_tuple = PyTuple::new(py, args.iter().map(|v| v.to_object(py)));
    let res = py_type.call1(args_tuple).unwrap_or_else(|e| {
        panic!(
            "Core type constructor `{}` failed: {:?}",
            py_type.name().unwrap(),
            e
        );
    });
    Value::new(res.into_py(py))
}

lazy_static! {
    pub static ref INTERNS: Interns = Interns::new();
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
pub struct PyGeneratorResponseCall(RefCell<Option<Call>>);

#[pymethods]
impl PyGeneratorResponseCall {
    #[new]
    fn __new__(
        py: Python,
        rule_id: String,
        output_type: &PyType,
        args: &PyTuple,
        input_arg0: Option<&PyAny>,
        input_arg1: Option<&PyAny>,
    ) -> PyResult<Self> {
        let output_type = TypeId::new(output_type);
        let (args, args_arity) = if args.is_empty() {
            (None, 0)
        } else {
            (
                Some(args.extract::<Key>()?),
                args.len().try_into().map_err(|e| {
                    PyException::new_err(format!("Too many explicit arguments for {rule_id}: {e}"))
                })?,
            )
        };
        let (input_types, inputs) = interpret_get_inputs(py, input_arg0, input_arg1)?;

        Ok(Self(RefCell::new(Some(Call {
            rule_id: RuleId::from_string(rule_id),
            output_type,
            args,
            args_arity,
            input_types,
            inputs,
        }))))
    }
}

impl PyGeneratorResponseCall {
    fn take(&self) -> Result<Call, String> {
        self.0
            .borrow_mut()
            .take()
            .ok_or_else(|| "A `Call` may only be consumed once.".to_owned())
    }
}

// Contains a `RefCell<Option<Get>>` in order to allow us to `take` the content without cloning.
#[pyclass(subclass)]
pub struct PyGeneratorResponseGet(RefCell<Option<Get>>);

impl PyGeneratorResponseGet {
    fn take(&self) -> Result<Get, String> {
        self.0
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
        Ok(self
            .0
            .borrow()
            .as_ref()
            .ok_or_else(|| {
                PyException::new_err(
                    "A `Get` may not be consumed after being provided to the @rule engine.",
                )
            })?
            .output
            .as_py_type(py))
    }

    #[getter]
    fn input_types<'p>(&'p self, py: Python<'p>) -> PyResult<Vec<&'p PyType>> {
        Ok(self
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
            .collect())
    }

    #[getter]
    fn inputs(&self) -> PyResult<Vec<PyObject>> {
        Ok(self
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
            .collect())
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

#[derive(Debug)]
pub struct Call {
    pub rule_id: RuleId,
    pub output_type: TypeId,
    // A tuple of positional arguments.
    pub args: Option<Key>,
    // The number of positional arguments which have been provided.
    pub args_arity: u16,
    pub input_types: SmallVec<[TypeId; 2]>,
    pub inputs: SmallVec<[Key; 2]>,
}

impl fmt::Display for Call {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
        write!(f, "Call({}, {}", self.rule_id, self.output_type)?;
        match self.input_types.len() {
            0 => write!(f, ")"),
            1 => write!(f, ", {}, {})", self.input_types[0], self.inputs[0]),
            _ => write!(
                f,
                ", {{{}}})",
                self.input_types
                    .iter()
                    .zip(self.inputs.iter())
                    .map(|(t, k)| { format!("{k}: {t}") })
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
        }
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
                self.input_types
                    .iter()
                    .zip(self.inputs.iter())
                    .map(|(t, k)| { format!("{k}: {t}") })
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
        }
    }
}

pub enum GetOrGenerator {
    Get(Get),
    Generator(Value),
}

pub enum GeneratorResponse {
    /// The generator has completed with the given value of the given type.
    Break(Value, TypeId),
    /// The generator is awaiting a call to a known rule.
    Call(Call),
    /// The generator is awaiting a call to an unknown rule.
    Get(Get),
    /// The generator is awaiting calls to a series of generators or Gets, all of which will
    /// produce `Call`s or `Get`s.
    ///
    /// The generators used in this position will either be call-by-name `@rule` stubs (which will
    /// immediately produce a `Call`, and then return its value), or async "rule helpers", which
    /// might use either the call-by-name or `Get` syntax.
    All(Vec<GetOrGenerator>),
}
