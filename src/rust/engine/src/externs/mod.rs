// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// File-specific allowances to silence internal warnings of `[pyclass]`.
#![allow(clippy::used_underscore_binding)]

use futures::FutureExt;
use futures::future::{BoxFuture, Future};
use pyo3::FromPyObject;
use pyo3::exceptions::{PyAssertionError, PyException, PyStopIteration, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::sync::GILProtected;
use pyo3::types::{PyBool, PyBytes, PyDict, PySequence, PyString, PyTuple, PyType};
use pyo3::{create_exception, import_exception, intern};
use smallvec::{SmallVec, smallvec};
use std::cell::{Ref, RefCell};
use std::collections::BTreeMap;
use std::convert::TryInto;
use std::fmt;
use std::sync::LazyLock;

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
mod unions;
pub mod workunits;

pub fn register(py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyFailure>()?;
    m.add_class::<PyGeneratorResponseNativeCall>()?;
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
            Failure::Throw { val, .. } => PyErr::from_value(val.bind(py).to_owned()),
            f @ (Failure::Invalidated | Failure::MissingDigest { .. }) => {
                EngineError::new_err(format!("{f}"))
            }
        }
    }
}

// TODO: We import this exception type because `pyo3` doesn't support declaring exceptions with
// additional fields. See https://github.com/PyO3/pyo3/issues/295
import_exception!(pants.base.exceptions, NativeEngineFailure);

pub fn equals(h1: &Bound<'_, PyAny>, h2: &Bound<'_, PyAny>) -> bool {
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
pub fn is_union(py: Python, v: &Bound<'_, PyType>) -> PyResult<bool> {
    let is_union_for_attr = intern!(py, "_is_union_for");
    if !v.hasattr(is_union_for_attr)? {
        return Ok(false);
    }

    let is_union_for = v.getattr(is_union_for_attr)?;
    Ok(is_union_for.is(v))
}

/// If the given type is a @union, return its in-scope types.
///
/// This function is also implemented in Python as `pants.engine.unions.union_in_scope_types`.
pub fn union_in_scope_types<'py>(
    py: Python<'py>,
    v: &Bound<'py, PyType>,
) -> PyResult<Option<Vec<Bound<'py, PyType>>>> {
    if !is_union(py, v)? {
        return Ok(None);
    }

    let union_in_scope_types: Vec<Bound<'_, PyType>> =
        v.getattr(intern!(py, "_union_in_scope_types"))?.extract()?;
    Ok(Some(union_in_scope_types))
}

pub fn store_tuple(py: Python, values: Vec<Value>) -> PyResult<Value> {
    let arg_handles: Vec<_> = values
        .into_iter()
        .map(|v| v.consume_into_py_object(py))
        .collect();
    Ok(Value::from(PyTuple::new(py, &arg_handles)?.into_any()))
}

/// Store a slice containing 2-tuples of (key, value) as a Python dictionary.
pub fn store_dict(
    py: Python,
    keys_and_values: impl IntoIterator<Item = (Value, Value)>,
) -> PyResult<Value> {
    let dict = PyDict::new(py);
    for (k, v) in keys_and_values {
        dict.set_item(k.consume_into_py_object(py), v.consume_into_py_object(py))?;
    }
    Ok(Value::from(dict.into_any()))
}

/// Store an opaque buffer of bytes to pass to Python. This will end up as a Python `bytes`.
pub fn store_bytes(py: Python, bytes: &[u8]) -> Value {
    Value::from(PyBytes::new(py, bytes).into_any())
}

/// Store a buffer of utf8 bytes to pass to Python. This will end up as a Python `str`.
pub fn store_utf8(py: Python, utf8: &str) -> Value {
    Value::from(PyString::new(py, utf8).into_any())
}

pub fn store_u64(py: Python, val: u64) -> Value {
    Value::from(val.into_pyobject(py).unwrap())
}

pub fn store_i64(py: Python, val: i64) -> Value {
    Value::from(val.into_pyobject(py).unwrap())
}

pub fn store_bool(py: Python, val: bool) -> Value {
    Value::from(PyBool::new(py, val))
}

///
/// Gets an attribute of the given value as the given type.
///
pub fn getattr<'py, T>(value: &Bound<'py, PyAny>, field: &str) -> Result<T, String>
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
pub fn collect_iterable<'py>(value: &Bound<'py, PyAny>) -> Result<Vec<Bound<'py, PyAny>>, String> {
    match value.try_iter() {
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
pub fn getattr_from_str_frozendict<'py, T: FromPyObject<'py>>(
    value: &Bound<'py, PyAny>,
    field: &str,
) -> BTreeMap<String, T> {
    let frozendict: Bound<PyAny> = getattr(value, field).unwrap();
    let pydict: Bound<PyDict> = getattr(&frozendict, "_data").unwrap();
    pydict
        .items()
        .into_iter()
        .map(|kv_pair| kv_pair.extract().unwrap())
        .collect()
}

pub fn getattr_as_optional_string(
    value: &Bound<'_, PyAny>,
    field: &str,
) -> PyResult<Option<String>> {
    // TODO: It's possible to view a python string as a `Cow<str>`, so we could avoid actually
    // cloning in some cases.
    value.getattr(field)?.extract()
}

/// Call the equivalent of `str()` on an arbitrary Python object.
///
/// Converts `None` to the empty string.
pub fn val_to_str(obj: &Bound<'_, PyAny>) -> String {
    if obj.is_none() {
        return "".to_string();
    }
    obj.str().unwrap().extract().unwrap()
}

pub fn val_to_log_level(obj: &Bound<'_, PyAny>) -> Result<log::Level, String> {
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
    Value::from(
        IntrinsicError::new_err(msg)
            .into_pyobject(py)
            .expect("Construct PyErr"),
    )
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
    py: Python<'_>,
    generator_type: &TypeId,
    generator: &Value,
    input: GeneratorInput,
) -> Result<GeneratorResponse, Failure> {
    let (response_unhandled, maybe_thrown) = match input {
        GeneratorInput::Arg(arg) => {
            let response = generator
                .bind(py)
                .getattr(intern!(py, "send"))?
                .call1((&arg,));
            (response, None)
        }
        GeneratorInput::Err(err) => {
            let throw_method = generator.bind(py).getattr(intern!(py, "throw"))?;
            if err.is_instance_of::<NativeEngineFailure>(py) {
                let throw = err
                    .value(py)
                    .getattr(intern!(py, "failure"))?
                    .extract::<PyRef<PyFailure>>()?
                    .get_error(py);
                let response = throw_method.call1((&throw,));
                (response, Some((throw, err)))
            } else {
                let response = throw_method.call1((err,));
                (response, None)
            }
        }
        GeneratorInput::Initial => {
            let response = generator
                .bind(py)
                .getattr(intern!(py, "send"))?
                .call1((&py.None(),));
            (response, None)
        }
    };

    let response = match response_unhandled {
        Err(e) if e.is_instance_of::<PyStopIteration>(py) => {
            let value = e.into_value(py).getattr(py, intern!(py, "value"))?;
            let type_id = TypeId::new(&value.bind(py).get_type());
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

    let result = if let Ok(call) = response.extract::<PyRef<PyGeneratorResponseCall>>() {
        Ok(GeneratorResponse::Call(call.take(py)?))
    } else if let Ok(get) = response.extract::<PyRef<PyGeneratorResponseGet>>() {
        // It isn't necessary to differentiate between `Get` and `Effect` here, as the static
        // analysis of `@rule`s has already validated usage.
        Ok(GeneratorResponse::Get(get.take(py)?))
    } else if let Ok(call) = response.extract::<PyRef<PyGeneratorResponseNativeCall>>() {
        Ok(GeneratorResponse::NativeCall(call.take(py)?))
    } else if let Ok(get_multi) = response.downcast::<PySequence>() {
        // Was an `All` or `MultiGet`.
        let gogs = get_multi
            .try_iter()?
            .map(|gog| {
                let gog = gog?;
                // TODO: Find a better way to check whether something is a coroutine... this seems
                // unnecessarily awkward.
                if gog.is_instance(&generator_type.as_py_type(py))? {
                    Ok(GetOrGenerator::Generator(Value::new(gog.unbind())))
                } else if let Ok(get) = gog.extract::<PyRef<PyGeneratorResponseGet>>() {
                    Ok(GetOrGenerator::Get(
                        get.take(py).map_err(PyException::new_err)?,
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
    let args_tuple = PyTuple::new(py, args.iter().map(|v| v.bind(py))).unwrap_or_else(|e| {
        panic!("Core type constructor `PyTuple` failed: {e:?}",);
    });
    let res = py_type.call1(args_tuple).unwrap_or_else(|e| {
        panic!(
            "Core type constructor `{}` failed: {:?}",
            py_type.name().unwrap(),
            e
        );
    });
    Value::from(&res)
}

pub static INTERNS: LazyLock<Interns> = LazyLock::new(Interns::new);

/// Interprets the `Get` and `implicitly(..)` syntax, which reduces to two optional positional
/// arguments, and results in input types and inputs.
#[allow(clippy::type_complexity)]
fn interpret_get_inputs(
    py: Python,
    input_arg0: Option<Bound<'_, PyAny>>,
    input_arg1: Option<Bound<'_, PyAny>>,
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
                    input_types.push(TypeId::new(
                        &declared_type
                            .downcast::<PyType>()
                            .map_err(|_| {
                                PyTypeError::new_err(
                "Invalid Get. Because the second argument was a dict, we expected the keys of the \
            dict to be the Get inputs, and the values of the dict to be the declared \
            types of those inputs.",
              )
                            })?
                            .as_borrowed(),
                    ));
                    inputs.push(INTERNS.key_insert(py, value.into())?);
                }
                Ok((input_types, inputs))
            } else {
                Ok((
                    smallvec![TypeId::new(&input_arg0.get_type().as_borrowed())],
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
            if !declared_type.is(&actual_type) && !is_union(py, declared_type)? {
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

#[pyclass]
pub struct PyGeneratorResponseNativeCall(GILProtected<RefCell<Option<NativeCall>>>);

impl PyGeneratorResponseNativeCall {
    pub fn new(call: impl Future<Output = Result<Value, Failure>> + 'static + Send) -> Self {
        Self(GILProtected::new(RefCell::new(Some(NativeCall {
            call: call.boxed(),
        }))))
    }

    fn take(&self, py: Python<'_>) -> Result<NativeCall, String> {
        self.0
            .get(py)
            .borrow_mut()
            .take()
            .ok_or_else(|| "A `NativeCall` may only be consumed once.".to_owned())
    }
}

#[pymethods]
impl PyGeneratorResponseNativeCall {
    fn __await__(self_: PyRef<'_, Self>) -> PyRef<'_, Self> {
        self_
    }

    fn __iter__(self_: PyRef<'_, Self>) -> PyRef<'_, Self> {
        self_
    }

    fn __next__(self_: PyRef<'_, Self>) -> Option<PyRef<'_, Self>> {
        Some(self_)
    }

    fn send(&self, py: Python<'_>, value: PyObject) -> PyResult<()> {
        let args = PyTuple::new(py, [value])?.into_pyobject(py)?.unbind();
        Err(PyStopIteration::new_err(args))
    }
}

#[pyclass(subclass)]
pub struct PyGeneratorResponseCall(GILProtected<RefCell<Option<Call>>>);

impl PyGeneratorResponseCall {
    fn borrow_inner<'py>(&'py self, py: Python<'py>) -> PyResult<Ref<'py, Call>> {
        let inner: Ref<'py, _> = self.0.get(py).borrow();

        Ref::filter_map(inner, |o: &Option<Call>| o.as_ref()).map_err(|_| {
            PyException::new_err(
                "A `Call` may not be consumed after being provided to the @rule engine.",
            )
        })
    }
}

#[pymethods]
impl PyGeneratorResponseCall {
    #[new]
    #[pyo3(signature = (rule_id, output_type, args, input_arg0=None, input_arg1=None))]
    fn __new__(
        py: Python,
        rule_id: String,
        output_type: &Bound<'_, PyType>,
        args: &Bound<'_, PyTuple>,
        input_arg0: Option<Bound<'_, PyAny>>,
        input_arg1: Option<Bound<'_, PyAny>>,
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

        Ok(Self(GILProtected::new(RefCell::new(Some(Call {
            rule_id: RuleId::from_string(rule_id),
            output_type,
            args,
            args_arity,
            input_types,
            inputs,
        })))))
    }

    #[getter]
    fn rule_id(&self, py: Python) -> PyResult<String> {
        // TODO: Currently this is only called in test infrastructure (specifically, by
        // rule_runner.py). But if this ends up being used in a performance sensitive
        // code path, consider denormalizing the rule_id to avoid this copy.
        Ok(self.borrow_inner(py)?.rule_id.as_str().to_owned())
    }

    #[getter]
    fn output_type<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyType>> {
        Ok(self.borrow_inner(py)?.output_type.as_py_type(py))
    }

    #[getter]
    fn input_types<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyType>>> {
        Ok(self
            .borrow_inner(py)?
            .input_types
            .iter()
            .map(|t| t.as_py_type(py))
            .collect())
    }

    #[getter]
    fn inputs(&self, py: Python<'_>) -> PyResult<Vec<PyObject>> {
        let inner = self.borrow_inner(py)?;
        let args: Vec<PyObject> = inner.args.as_ref().map_or_else(
            || Ok(Vec::default()),
            |args| args.to_py_object().extract(py),
        )?;
        Ok(args
            .into_iter()
            .chain(inner.inputs.iter().map(Key::to_py_object))
            .collect())
    }
}

impl PyGeneratorResponseCall {
    fn take(&self, py: Python<'_>) -> Result<Call, String> {
        self.0
            .get(py)
            .borrow_mut()
            .take()
            .ok_or_else(|| "A `Call` may only be consumed once.".to_owned())
    }
}

// Contains a `RefCell<Option<Get>>` in order to allow us to `take` the content without cloning.
#[pyclass(subclass)]
pub struct PyGeneratorResponseGet(GILProtected<RefCell<Option<Get>>>);

impl PyGeneratorResponseGet {
    fn take(&self, py: Python<'_>) -> Result<Get, String> {
        self.0
            .get(py)
            .borrow_mut()
            .take()
            .ok_or_else(|| "A `Get` may only be consumed once.".to_owned())
    }
}

#[pymethods]
impl PyGeneratorResponseGet {
    #[new]
    #[pyo3(signature = (product, input_arg0=None, input_arg1=None))]
    fn __new__(
        py: Python,
        product: &Bound<'_, PyAny>,
        input_arg0: Option<Bound<'_, PyAny>>,
        input_arg1: Option<Bound<'_, PyAny>>,
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

        Ok(Self(GILProtected::new(RefCell::new(Some(Get {
            output,
            input_types,
            inputs,
        })))))
    }

    #[getter]
    fn output_type<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyType>> {
        Ok(self
            .0
            .get(py)
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
    fn input_types<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyType>>> {
        Ok(self
            .0
            .get(py)
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
    fn inputs(&self, py: Python<'_>) -> PyResult<Vec<PyObject>> {
        Ok(self
            .0
            .get(py)
            .borrow()
            .as_ref()
            .ok_or_else(|| {
                PyException::new_err(
                    "A `Get` may not be consumed after being provided to the @rule engine.",
                )
            })?
            .inputs
            .iter()
            .map(Key::to_py_object)
            .collect())
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        Ok(format!(
            "{}",
            self.0.get(py).borrow().as_ref().ok_or_else(|| {
                PyException::new_err(
                    "A `Get` may not be consumed after being provided to the @rule engine.",
                )
            })?
        ))
    }
}

pub struct NativeCall {
    pub call: BoxFuture<'static, Result<Value, Failure>>,
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
    /// The generator is awaiting a call to a unknown native function.
    NativeCall(NativeCall),
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
