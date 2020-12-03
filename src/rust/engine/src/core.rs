// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use fnv::FnvHasher;

use std::collections::HashSet;
use std::convert::AsRef;
use std::ops::Deref;
use std::sync::Arc;
use std::{fmt, hash};

use crate::externs;

use cpython::{
  FromPyObject, PyClone, PyDict, PyErr, PyObject, PyResult, PyType, Python, ToPyObject,
};
use indexmap::{IndexMap, IndexSet};
use smallvec::SmallVec;

pub type FNV = hash::BuildHasherDefault<FnvHasher>;

///
/// Params represent a TypeId->Key map.
///
/// For efficiency and hashability, they're stored as sorted Keys (with distinct TypeIds).
///
#[repr(C)]
#[derive(Clone, Debug, Default, Eq, Hash, PartialEq)]
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
            "Values used as `Params` must have distinct types, but the following values had the same type (`{}`):\n  {}\n  {}",
            externs::type_to_str(*prev.type_id()),
            externs::key_to_str(prev),
            externs::key_to_str(param)
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
  /// Adds the given param Key to these Params, replacing an existing param with the same type if
  /// it exists.
  ///
  pub fn put(&mut self, param: Key) {
    match self.binary_search(param.type_id) {
      Ok(idx) => self.0[idx] = param,
      Err(idx) => self.0.insert(idx, param),
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
    self
      .0
      .binary_search_by(|probe| probe.type_id().cmp(&type_id))
  }

  pub fn type_ids<'a>(&'a self) -> impl Iterator<Item = TypeId> + 'a {
    self.0.iter().map(|k| *k.type_id())
  }
}

///
pub fn display_sorted_in_parens<T>(items: T) -> String
where
  T: Iterator,
  T::Item: fmt::Display,
{
  let mut items: Vec<_> = items.map(|p| format!("{}", p)).collect();
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

///
/// A pointer to an underlying PyTypeObject instance.
///
/// NB: This is a void pointer because the `cpython::ffi::PyTypeObject` is not public.
///
#[derive(Clone, Copy, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct TypeId(*mut std::ffi::c_void);

unsafe impl Send for TypeId {}
unsafe impl Sync for TypeId {}

impl TypeId {
  pub fn as_py_type(&self, py: Python) -> PyType {
    // NB: Dereferencing a pointer to a PyTypeObject is safe as long as the module defining the
    // type is not unloaded. That is true today, but would not be if we implemented support for hot
    // reloading of plugins.
    unsafe { PyType::from_type_ptr(py, self.0 as _) }
  }

  fn pretty_print(self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "{}", externs::type_to_str(self))
  }
}

impl From<&PyType> for TypeId {
  fn from(py_type: &PyType) -> Self {
    TypeId(py_type.as_type_ptr() as *mut std::ffi::c_void)
  }
}

impl rule_graph::TypeId for TypeId {
  ///
  /// Render a string for a collection of TypeIds.
  ///
  fn display<I>(type_ids: I) -> String
  where
    I: Iterator<Item = TypeId>,
  {
    display_sorted_in_parens(type_ids)
  }
}

impl fmt::Debug for TypeId {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    self.pretty_print(f)
  }
}

impl fmt::Display for TypeId {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    self.pretty_print(f)
  }
}

/// An identifier for a Python function.
#[repr(C)]
#[derive(Clone, Copy, Eq, Hash, PartialEq)]
pub struct Function(pub Key);

impl Function {
  /// A Python function's module, e.g. `project.app`.
  pub fn module(&self) -> String {
    let val = externs::val_for(&self.0);
    externs::getattr_as_string(&val, "__module__")
  }

  /// A Python function's name, without its module.
  pub fn name(&self) -> String {
    let val = externs::val_for(&self.0);
    externs::getattr_as_string(&val, "__name__")
  }

  /// The line number of a Python function's first line.
  pub fn line_number(&self) -> u64 {
    let val = externs::val_for(&self.0);
    // NB: this is a custom dunder method that Python code should populate before sending the
    // function (e.g. an `@rule`) through FFI.
    externs::getattr(&val, "__line_number__").unwrap()
  }

  /// The function represented as `path.to.module:lineno:func_name`.
  pub fn full_name(&self) -> String {
    format!("{}:{}:{}", self.module(), self.line_number(), self.name())
  }
}

impl fmt::Display for Function {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "{}()", self.full_name())
  }
}

impl fmt::Debug for Function {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "{}()", self.full_name())
  }
}

///
/// An interned key for a Value for use as a key in HashMaps and sets.
///
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Key {
  id: Id,
  type_id: TypeId,
}

impl fmt::Debug for Key {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "{}", externs::key_to_str(self))
  }
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

impl fmt::Display for Key {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "{}", externs::key_to_str(self))
  }
}

impl Key {
  pub fn new(id: Id, type_id: TypeId) -> Key {
    Key { id, type_id }
  }

  pub fn id(&self) -> Id {
    self.id
  }

  pub fn type_id(&self) -> &TypeId {
    &self.type_id
  }
}

///
/// We wrap PyObject (which cannot be cloned without acquiring the GIL) in an Arc in order to avoid
/// accessing the Gil in many cases.
///
#[derive(Clone)]
pub struct Value(Arc<PyObject>);

impl Value {
  pub fn new(handle: PyObject) -> Value {
    Value(Arc::new(handle))
  }

  // NB: Longer name because overloaded in a few places.
  pub fn consume_into_py_object(self, py: Python) -> PyObject {
    match Arc::try_unwrap(self.0) {
      Ok(handle) => handle,
      Err(arc_handle) => arc_handle.clone_ref(py),
    }
  }
}

impl PartialEq for Value {
  fn eq(&self, other: &Value) -> bool {
    externs::equals(&self.0, &other.0)
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
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "{}", externs::val_to_str(&self.as_ref()))
  }
}

impl fmt::Display for Value {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "{}", externs::val_to_str(&self.as_ref()))
  }
}

impl FromPyObject<'_> for Value {
  fn extract(py: Python, obj: &PyObject) -> PyResult<Self> {
    Ok(obj.clone_ref(py).into())
  }
}

impl ToPyObject for &Value {
  type ObjectType = PyObject;
  fn to_py_object(&self, py: Python) -> PyObject {
    self.0.clone_ref(py)
  }
}

impl From<Value> for PyObject {
  fn from(value: Value) -> Self {
    match Arc::try_unwrap(value.0) {
      Ok(handle) => handle,
      Err(arc_handle) => {
        let gil = Python::acquire_gil();
        arc_handle.clone_ref(gil.python())
      }
    }
  }
}

impl From<PyObject> for Value {
  fn from(handle: PyObject) -> Self {
    Value::new(handle)
  }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Failure {
  /// A Node failed because a filesystem change invalidated it or its inputs.
  /// A root requestor should usually immediately retry their request.
  Invalidated,
  /// An error was thrown.
  Throw {
    // A python exception value, which might have a python-level stacktrace
    val: Value,
    // A pre-formatted python exception traceback.
    python_traceback: String,
    // A stack of engine-side "frame" information generated from Nodes.
    engine_traceback: Vec<String>,
  },
}

impl Failure {
  ///
  /// Consumes this Failure to produce a new Failure with an additional engine_traceback entry.
  ///
  pub fn with_pushed_frame(self, frame: &impl fmt::Display) -> Failure {
    match self {
      Failure::Invalidated => Failure::Invalidated,
      Failure::Throw {
        val,
        python_traceback,
        mut engine_traceback,
      } => {
        engine_traceback.push(format!("{}", frame));
        Failure::Throw {
          val,
          python_traceback,
          engine_traceback,
        }
      }
    }
  }
}

impl Failure {
  pub fn from_py_err(py_err: PyErr) -> Failure {
    let gil = Python::acquire_gil();
    let py = gil.python();
    Failure::from_py_err_with_gil(py, py_err)
  }
  pub fn from_py_err_with_gil(py: Python, mut py_err: PyErr) -> Failure {
    let val = Value::from(py_err.instance(py));
    let python_traceback = if let Some(tb) = py_err.ptraceback.as_ref() {
      let locals = PyDict::new(py);
      locals
        .set_item(py, "traceback", py.import("traceback").unwrap())
        .unwrap();
      locals.set_item(py, "tb", tb).unwrap();
      locals.set_item(py, "val", &val).unwrap();
      py.eval(
        "''.join(traceback.format_exception(etype=None, value=val, tb=tb))",
        None,
        Some(&locals),
      )
      .unwrap()
      .extract::<String>(py)
      .unwrap()
    } else {
      Self::native_traceback(&externs::val_to_str(val.as_ref()))
    };
    Failure::Throw {
      val,
      python_traceback,
      engine_traceback: Vec::new(),
    }
  }

  pub fn native_traceback(msg: &str) -> String {
    format!(
      "Traceback (no traceback):\n  <pants native internals>\nException: {}",
      msg
    )
  }
}

impl fmt::Display for Failure {
  fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
    match self {
      Failure::Invalidated => write!(f, "Giving up on retrying due to changed files."),
      Failure::Throw { val, .. } => write!(f, "{}", externs::val_to_str(val.as_ref())),
    }
  }
}

pub fn throw(msg: &str) -> Failure {
  Failure::Throw {
    val: externs::create_exception(msg),
    python_traceback: Failure::native_traceback(msg),
    engine_traceback: Vec::new(),
  }
}

///
/// Given a graph represented as an adjacency list, return a collection of cyclic paths.
///
pub fn cyclic_paths<N: hash::Hash + Eq + Copy>(adjacencies: IndexMap<N, Vec<N>>) -> Vec<Vec<N>> {
  let mut cyclic_paths = Vec::new();
  let mut path_stack = IndexSet::new();
  let mut visited = HashSet::new();

  for node in adjacencies.keys() {
    cyclic_paths_visit(
      *node,
      &adjacencies,
      &mut cyclic_paths,
      &mut path_stack,
      &mut visited,
    );
  }

  cyclic_paths
}

fn cyclic_paths_visit<N: hash::Hash + Eq + Copy>(
  node: N,
  adjacencies: &IndexMap<N, Vec<N>>,
  cyclic_paths: &mut Vec<Vec<N>>,
  path_stack: &mut IndexSet<N>,
  visited: &mut HashSet<N>,
) {
  if visited.contains(&node) {
    if path_stack.contains(&node) {
      cyclic_paths.push(
        path_stack
          .iter()
          .cloned()
          .chain(std::iter::once(node))
          .collect::<Vec<_>>(),
      );
    }
    return;
  }
  path_stack.insert(node);
  visited.insert(node);

  if let Some(adjacent) = adjacencies.get(&node) {
    for dep_node in adjacent {
      cyclic_paths_visit(*dep_node, adjacencies, cyclic_paths, path_stack, visited);
    }
  }

  path_stack.remove(&node);
}
