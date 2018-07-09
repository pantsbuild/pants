// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use fnv::FnvHasher;

use std::collections::HashMap;
use std::ops::Deref;
use std::sync::Arc;
use std::{fmt, hash};

use externs;
use handles::Handle;

pub type FNV = hash::BuildHasherDefault<FnvHasher>;

///
/// Variants represent a string->string map. For hashability purposes, they're stored
/// as sorted string tuples.
///
#[repr(C)]
#[derive(Clone, Debug, Default, Eq, Hash, PartialEq)]
pub struct Variants(pub Vec<(String, String)>);

impl Variants {
  ///
  /// Merges right over self (by key, and then sorted by key).
  ///
  /// TODO: Unused: see https://github.com/pantsbuild/pants/issues/4020
  ///
  #[allow(dead_code)]
  pub fn merge(&self, right: Variants) -> Variants {
    // Merge.
    let mut left: HashMap<_, _, FNV> = self.0.iter().cloned().collect();
    left.extend(right.0);
    // Convert back to a vector and sort.
    let mut result: Vec<(String, String)> = left.into_iter().collect();
    result.sort();
    Variants(result)
  }

  pub fn find(&self, key: &str) -> Option<&str> {
    self
      .0
      .iter()
      .find(|&&(ref k, _)| k == key)
      .map(|&(_, ref v)| v.as_str())
  }
}

pub type Id = u64;

// The type of a python object (which itself has a type, but which is not represented
// by a Key, because that would result in a infinitely recursive structure.)
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct TypeId(pub Id);

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
  fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
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
  /// There was no valid combination of rules to satisfy a request.
  Noop(Noop),
  /// A rule raised an exception.
  Throw(Value, String),
}

// NB: enum members are listed in ascending priority order based on how likely they are
// to be useful to users.
#[derive(Clone, Copy, Eq, PartialEq, Ord, PartialOrd)]
pub enum Noop {
  NoTask,
  NoVariant,
  Cycle,
}

impl fmt::Debug for Noop {
  fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
    f.write_str(match self {
      &Noop::Cycle => "Dep graph contained a cycle.",
      &Noop::NoTask => "No task was available to compute the value.",
      &Noop::NoVariant => "A matching variant key was not configured in variants.",
    })
  }
}

pub fn throw(msg: &str) -> Failure {
  Failure::Throw(
    externs::create_exception(msg),
    format!(
      "Traceback (no traceback):\n  <pants native internals>\nException: {}",
      msg
    ).to_string(),
  )
}
