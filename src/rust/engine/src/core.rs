// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use fnv::FnvHasher;

use std::ops::Deref;
use std::sync::Arc;
use std::{fmt, hash};

use crate::externs;
use crate::handles::Handle;

use smallvec::{smallvec, SmallVec};

pub type FNV = hash::BuildHasherDefault<FnvHasher>;

///
/// Params represent a TypeId->Key map.
///
/// For efficiency and hashability, they're stored as sorted Keys (with distinct TypeIds), and
/// wrapped in an `Arc` that allows us to copy-on-write for param contents.
///
#[repr(C)]
#[derive(Clone, Debug, Default, Eq, Hash, PartialEq)]
pub struct Params(SmallVec<[Key; 4]>);

impl Params {
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

  pub fn new_single(param: Key) -> Params {
    Params(smallvec![param])
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

  ///
  /// Given a set of either param type or param value strings: sort, join, and render as one string.
  ///
  pub fn display(mut params: Vec<String>) -> String {
    match params.len() {
      0 => "()".to_string(),
      1 => params.pop().unwrap(),
      _ => {
        params.sort();
        format!("({})", params.join("+"))
      }
    }
  }
}

impl fmt::Display for Params {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(
      f,
      "{}",
      Self::display(self.0.iter().map(|k| format!("{}", k)).collect())
    )
  }
}

pub type Id = u64;

// The type of a python object (which itself has a type, but which is not represented
// by a Key, because that would result in a infinitely recursive structure.)
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct TypeId(pub Id);

impl fmt::Display for TypeId {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    if *self == ANY_TYPE {
      write!(f, "Any")
    } else {
      write!(f, "{}", externs::type_to_str(*self))
    }
  }
}

// On the python side, the 0th type id is used as an anonymous id
pub const ANY_TYPE: TypeId = TypeId(0);

// A type constraint, which a TypeId may or may-not satisfy.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct TypeConstraint(pub Key);

// An identifier for a python function.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Function(pub Key);

///
/// Wraps a type id for use as a key in HashMaps and sets.
///
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct Key {
  id: Id,
  type_id: TypeId,
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
/// A wrapper around a handle: soon to contain an Arc.
///
#[derive(Clone, Eq, PartialEq)]
pub struct Value(Arc<Handle>);

impl Value {
  pub fn new(handle: Handle) -> Value {
    Value(Arc::new(handle))
  }
}

impl Deref for Value {
  type Target = Handle;

  fn deref(&self) -> &Handle {
    &self.0
  }
}

impl fmt::Debug for Value {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "{}", externs::val_to_str(&self))
  }
}

///
/// Creates a Handle (which represents exclusive access) from a Value (which might be shared),
/// cloning if necessary.
///
impl From<Value> for Handle {
  fn from(value: Value) -> Self {
    match Arc::try_unwrap(value.0) {
      Ok(handle) => handle,
      Err(arc_handle) => externs::clone_val(&arc_handle),
    }
  }
}

impl From<Handle> for Value {
  fn from(handle: Handle) -> Self {
    Value::new(handle)
  }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Failure {
  /// A Node failed because a filesystem change invalidated it or its inputs.
  /// A root requestor should usually immediately retry their request.
  Invalidated,
  /// A rule raised an exception.
  Throw(Value, String),
}

impl fmt::Display for Failure {
  fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
    match self {
      Failure::Invalidated => write!(f, "Exhausted retries due to changed files."),
      Failure::Throw(exc, _) => write!(f, "{}", externs::val_to_str(exc)),
    }
  }
}

pub fn throw(msg: &str) -> Failure {
  Failure::Throw(
    externs::create_exception(msg),
    format!(
      "Traceback (no traceback):\n  <pants native internals>\nException: {}",
      msg
    ),
  )
}
