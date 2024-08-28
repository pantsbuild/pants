// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::convert::AsRef;
use std::ops::Deref;
use std::sync::Arc;
use std::{fmt, hash};

use deepsize::{known_deep_size, DeepSizeOf};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyType};
use pyo3::{FromPyObject, IntoPy, ToPyObject};
use smallvec::SmallVec;

use hashing::Digest;
use process_execution::ProcessError;
use store::StoreError;

use crate::externs;

///
/// Params represent a TypeId->Key map.
///
/// For efficiency and hashability, they're stored as sorted Keys (with distinct TypeIds).
///
#[derive(Clone, Debug, Default, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Params(SmallVec<[Key; 4]>);

impl<'x> Params {
    pub fn new<I: IntoIterator<Item = Key>>(param_inputs: I) -> Result<Params, String> {
        let mut params = param_inputs.into_iter().collect::<SmallVec<[Key; 4]>>();
        params.sort_by_key(|k| *k.type_id());

        if params.len() > 1 {
            let mut prev = &params[0];
            for param in &params[1..] {
                if param.type_id() == prev.type_id() {
                    return Err(format!(
                        "Values used as `Params` must have distinct types, but the following \
            values had the same type (`{}`):\n  {}\n  {}",
                        prev.type_id(),
                        prev,
                        param,
                    ));
                }
                prev = param;
            }
        }

        Ok(Params(params))
    }

    pub fn keys(&'x self) -> impl Iterator<Item = &'x Key> {
        self.0.iter()
    }

    ///
    /// Adds the given param Keys to these Params, replacing existing params with the same type if
    /// they exist.
    ///
    /// TODO: This is currently O(N^2 * M) for N existing Params and M added params, but both N and M
    /// are expected to be small. Should microbenchmark at some point.
    ///
    pub fn extend(&mut self, params: impl IntoIterator<Item = Key>) {
        for param in params {
            match self.binary_search(param.type_id) {
                Ok(idx) => self.0[idx] = param,
                Err(idx) => self.0.insert(idx, param),
            }
        }
    }

    ///
    /// Filters this Params object in-place to contain only params matching the given predicate.
    ///
    pub fn retain<F: FnMut(&mut Key) -> bool>(&mut self, f: F) {
        self.0.retain(f)
    }

    ///
    /// Returns the Key for the given TypeId if it is represented in this set of Params.
    ///
    pub fn find(&self, type_id: TypeId) -> Option<&Key> {
        self.binary_search(type_id).ok().map(|idx| &self.0[idx])
    }

    fn binary_search(&self, type_id: TypeId) -> Result<usize, usize> {
        self.0
            .binary_search_by(|probe| probe.type_id().cmp(&type_id))
    }

    pub fn type_ids(&self) -> impl Iterator<Item = TypeId> + '_ {
        self.0.iter().map(|k| *k.type_id())
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

pub fn display_sorted_in_parens<T>(items: T) -> String
where
    T: Iterator,
    T::Item: fmt::Display,
{
    let mut items: Vec<_> = items.map(|p| format!("{p}")).collect();
    match items.len() {
        0 => "()".to_string(),
        1 => items.pop().unwrap(),
        _ => {
            items.sort();
            format!("({})", items.join(", "))
        }
    }
}

impl fmt::Display for Params {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Params{}", display_sorted_in_parens(self.0.iter()))
    }
}

pub type Id = u64;

/// A pointer to an underlying PyTypeObject instance.
#[derive(Clone, Copy, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct TypeId(*mut pyo3::ffi::PyTypeObject);

known_deep_size!(8; TypeId);
unsafe impl Send for TypeId {}
unsafe impl Sync for TypeId {}

impl TypeId {
    pub fn new(py_type: &PyType) -> Self {
        py_type.into()
    }

    pub fn as_py_type<'py>(&self, py: Python<'py>) -> &'py PyType {
        // NB: Dereferencing a pointer to a PyTypeObject is safe as long as the module defining the
        // type is not unloaded. That is true today, but would not be if we implemented support for hot
        // reloading of plugins.
        unsafe { PyType::from_type_ptr(py, self.0) }
    }

    pub fn is_union(&self) -> bool {
        Python::with_gil(|py| externs::is_union(py, self.as_py_type(py)).unwrap())
    }

    pub fn union_in_scope_types(&self) -> Option<Vec<TypeId>> {
        Python::with_gil(|py| {
            externs::union_in_scope_types(py, self.as_py_type(py))
                .unwrap()
                .map(|types| types.into_iter().map(TypeId::new).collect())
        })
    }
}

impl From<&PyType> for TypeId {
    fn from(py_type: &PyType) -> Self {
        TypeId(py_type.as_type_ptr())
    }
}

impl fmt::Debug for TypeId {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        Python::with_gil(|py| {
            let name = self.as_py_type(py).name().unwrap();
            write!(f, "{name}")
        })
    }
}

impl fmt::Display for TypeId {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl rule_graph::TypeId for TypeId {
    /// Render a string for a collection of TypeIds.
    fn display<I>(type_ids: I) -> String
    where
        I: Iterator<Item = TypeId>,
    {
        display_sorted_in_parens(type_ids)
    }
}

/// An identifier for a Python function.
#[derive(Clone, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Function(pub Key);

impl Function {
    /// The function represented as `path.to.module:lineno:func_name`.
    pub fn full_name(&self) -> String {
        let (module, name, line_no) = Python::with_gil(|py| {
            let obj = (*self.0.value).as_ref(py);
            let module: String = externs::getattr(obj, "__module__").unwrap();
            let name: String = externs::getattr(obj, "__name__").unwrap();
            // NB: this is a custom dunder method that Python code should populate before sending the
            // function (e.g. an `@rule`) through FFI.
            let line_no: u64 = externs::getattr(obj, "__line_number__").unwrap();
            (module, name, line_no)
        });
        format!("{module}:{line_no}:{name}")
    }
}

impl fmt::Debug for Function {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "{}()", self.full_name())
    }
}

impl fmt::Display for Function {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

/// An interned key for a Value for use as a key in HashMaps and sets.
#[derive(Clone, DeepSizeOf)]
pub struct Key {
    id: Id,
    type_id: TypeId,
    pub value: Value,
}

impl Eq for Key {}

impl PartialEq for Key {
    fn eq(&self, other: &Key) -> bool {
        self.id == other.id
    }
}

impl hash::Hash for Key {
    fn hash<H: hash::Hasher>(&self, state: &mut H) {
        self.id.hash(state);
    }
}

impl fmt::Debug for Key {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "{:?}", self.value)
    }
}

impl fmt::Display for Key {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl<'source> FromPyObject<'source> for Key {
    fn extract(obj: &'source PyAny) -> PyResult<Self> {
        let py = obj.py();
        externs::INTERNS.key_insert(py, obj.into_py(py))
    }
}

impl Key {
    pub fn new(id: Id, type_id: TypeId, value: Value) -> Key {
        Key { id, type_id, value }
    }

    pub fn id(&self) -> Id {
        self.id
    }

    pub fn type_id(&self) -> &TypeId {
        &self.type_id
    }

    pub fn from_value(val: Value) -> PyResult<Key> {
        Python::with_gil(|py| externs::INTERNS.key_insert(py, val.consume_into_py_object(py)))
    }

    pub fn to_value(&self) -> Value {
        self.value.clone()
    }

    pub fn to_py_object(&self) -> PyObject {
        self.to_value().into()
    }
}

// NB: Although `PyObject` (aka `Py<PyAny>`) directly implements `Clone`, it's ~4% faster to wrap
// in `Arc` like this, because `Py<T>` internally acquires a (non-GIL) global lock during `Clone`
// and `Drop`.
#[derive(Clone)]
pub struct Value(Arc<PyObject>);

// NB: The size of objects held by a Graph is tracked independently, so we assert that each Value
// is only as large as its pointer.
known_deep_size!(8; Value);

impl Value {
    pub fn new(obj: PyObject) -> Value {
        Value(Arc::new(obj))
    }

    // NB: Longer name because overloaded in a few places.
    pub fn consume_into_py_object(self, py: Python) -> PyObject {
        match Arc::try_unwrap(self.0) {
            Ok(obj) => obj,
            Err(arc_handle) => arc_handle.clone_ref(py),
        }
    }
}

impl workunit_store::Value for Value {
    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}

impl PartialEq for Value {
    fn eq(&self, other: &Value) -> bool {
        Python::with_gil(|py| externs::equals((*self.0).as_ref(py), (*other.0).as_ref(py)))
    }
}

impl Eq for Value {}

impl Deref for Value {
    type Target = PyObject;

    fn deref(&self) -> &PyObject {
        &self.0
    }
}

impl AsRef<PyObject> for Value {
    fn as_ref(&self) -> &PyObject {
        &self.0
    }
}

impl fmt::Debug for Value {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        let repr = Python::with_gil(|py| {
            let obj = (*self.0).as_ref(py);
            externs::val_to_str(obj)
        });
        write!(f, "{repr}")
    }
}

impl fmt::Display for Value {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl<'source> FromPyObject<'source> for Value {
    fn extract(obj: &'source PyAny) -> PyResult<Self> {
        let py = obj.py();
        Ok(obj.into_py(py).into())
    }
}

impl ToPyObject for &Value {
    fn to_object(&self, py: Python) -> PyObject {
        self.0.clone_ref(py)
    }
}

impl From<Value> for PyObject {
    fn from(value: Value) -> Self {
        match Arc::try_unwrap(value.0) {
            Ok(obj) => obj,
            Err(arc_handle) => Python::with_gil(|py| arc_handle.clone_ref(py)),
        }
    }
}

impl From<PyObject> for Value {
    fn from(obj: PyObject) -> Self {
        Value::new(obj)
    }
}

impl IntoPy<PyObject> for &Value {
    fn into_py(self, py: Python) -> PyObject {
        (*self.0).as_ref(py).into_py(py)
    }
}

///
/// A short required name, and optional human readable description for a single frame of a Failure.
///
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FailureFrame {
    pub name: String,
    pub desc: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Failure {
    /// A Node failed because a filesystem change invalidated it or its inputs.
    /// A root requestor should usually immediately retry their request.
    Invalidated,
    /// A Digest was missing from the configured Stores. This error may be recoverable if the source
    /// of the missing Digest can be identified and retried (such as if it was produced by a cache).
    MissingDigest(String, Digest),
    /// An unclassified error was thrown.
    Throw {
        // A python exception value, which might have a python-level stacktrace
        val: Value,
        // A pre-formatted python exception traceback.
        python_traceback: String,
        // A stack of FailureFrames.
        engine_traceback: Vec<FailureFrame>,
    },
}

impl Failure {
    ///
    /// Consumes this Failure to produce a new Failure with an additional engine_traceback entry.
    ///
    pub fn with_pushed_frame(self, name: &str, desc: Option<String>) -> Failure {
        match self {
            Failure::Invalidated => Failure::Invalidated,
            md @ Failure::MissingDigest { .. } => {
                // MissingDigest errors are usually handled at the WrappedNode boundary by restarting the
                // producer of the missing digest. So a Failure will only end up with a new frame if it
                // traversed the node boundary for some reason, in which case it is safe to discard the
                // type information and convert into a Throw.
                throw(md.to_string()).with_pushed_frame(name, desc)
            }
            Failure::Throw {
                val,
                python_traceback,
                mut engine_traceback,
            } => {
                engine_traceback.push(FailureFrame {
                    name: name.to_owned(),
                    desc,
                });
                Failure::Throw {
                    val,
                    python_traceback,
                    engine_traceback,
                }
            }
        }
    }

    pub fn from_py_err_with_gil(py: Python, py_err: PyErr) -> Failure {
        // If this is a wrapped Failure, return it immediately.
        if let Some(failure) = Failure::from_wrapped_failure(py, &py_err) {
            return failure;
        }

        // Propagate the tracebacks from the causing error, if any.
        let (previous_ptraceback, engine_traceback) = if let Some(cause) = py_err.cause(py) {
            match Failure::from_wrapped_failure(py, &cause) {
                Some(Failure::Throw {
                    val,
                    engine_traceback,
                    python_traceback,
                }) => {
                    // Preserve tracebacks (both engine and python) from upstream error by using any existing
                    // engine traceback and restoring the original python exception cause.
                    py_err.set_cause(py, Some(PyErr::from_value((*val.0).as_ref(py))));
                    (
            format!(
              "{python_traceback}\nDuring handling of the above exception, another exception occurred:\n\n"
            ),
            engine_traceback,
          )
                }
                _ => ("".to_string(), Vec::new()),
            }
        } else {
            ("".to_string(), Vec::new())
        };

        let maybe_ptraceback = py_err
            .traceback(py)
            .map(|traceback| traceback.to_object(py));
        let val = Value::from(py_err.into_py(py));
        let python_traceback = if let Some(tb) = maybe_ptraceback {
            let locals = PyDict::new(py);
            locals
                .set_item("traceback", py.import("traceback").unwrap())
                .unwrap();
            locals.set_item("tb", tb).unwrap();
            locals.set_item("val", &val).unwrap();
            py.eval(
                "''.join(traceback.format_exception(None, value=val, tb=tb))",
                None,
                Some(locals),
            )
            .unwrap()
            .extract::<String>()
            .unwrap()
        } else {
            Self::native_traceback(&externs::val_to_str((*val).as_ref(py)))
        };
        Failure::Throw {
            val,
            python_traceback: previous_ptraceback + &python_traceback,
            engine_traceback,
        }
    }

    pub fn native_traceback(msg: &str) -> String {
        format!("Traceback (no traceback):\n  <pants native internals>\nException: {msg}")
    }
}

impl Failure {
    fn from_wrapped_failure(py: Python, py_err: &PyErr) -> Option<Failure> {
        match py_err.value(py).downcast::<externs::NativeEngineFailure>() {
            Ok(n_e_failure) => {
                let failure = n_e_failure
                    .getattr("failure")
                    .unwrap()
                    .extract::<externs::PyFailure>()
                    .unwrap();
                Some(failure.0)
            }
            _ => None,
        }
    }
}

impl fmt::Display for Failure {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            Failure::Invalidated => write!(f, "Giving up on retrying due to changed files."),
            Failure::MissingDigest(s, d) => {
                write!(f, "Missing digest: {s}: {d:?}")
            }
            Failure::Throw { val, .. } => {
                let repr = Python::with_gil(|py| {
                    let obj = (*val.0).as_ref(py);
                    externs::val_to_str(obj)
                });
                write!(f, "{repr}")
            }
        }
    }
}

impl From<ProcessError> for Failure {
    fn from(err: ProcessError) -> Self {
        match err {
            ProcessError::MissingDigest(s, d) => Self::MissingDigest(s, d),
            ProcessError::Unclassified(s) => throw(s),
        }
    }
}

impl From<StoreError> for Failure {
    fn from(err: StoreError) -> Self {
        match err {
            StoreError::MissingDigest(s, d) => Self::MissingDigest(s, d),
            StoreError::Unclassified(s) => throw(s),
        }
    }
}

impl From<Failure> for PyErr {
    fn from(err: Failure) -> Self {
        externs::NativeEngineFailure::new_err((err.to_string(), externs::PyFailure(err)))
    }
}

impl From<String> for Failure {
    fn from(err: String) -> Self {
        throw(err)
    }
}

impl From<PyErr> for Failure {
    fn from(py_err: PyErr) -> Self {
        Python::with_gil(|py| Failure::from_py_err_with_gil(py, py_err))
    }
}

pub fn throw(msg: String) -> Failure {
    let python_traceback = Failure::native_traceback(&msg);
    Python::with_gil(|py| Failure::Throw {
        val: externs::create_exception(py, msg),
        python_traceback,
        engine_traceback: Vec::new(),
    })
}
