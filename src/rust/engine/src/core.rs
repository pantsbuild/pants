// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use fnv::FnvHasher;

use std::collections::HashMap;
use std::{fmt, hash};
use std::ops::Drop;

use externs;
use handles::{Handle, enqueue_drop_handle};

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

  pub fn find(&self, key: &String) -> Option<&str> {
    self.0.iter().find(|&&(ref k, _)| k == key).map(
      |&(_, ref v)| {
        v.as_str()
      },
    )
  }
}

pub type Id = u64;

// The name of a field.
pub type Field = String;

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
/// Represents a handle to a python object, explicitly without equality or hashing. Whenever
/// the equality/identity of a Value matters, a Key should be computed for it and used instead.
///
/// Value implements Clone by calling out to a python extern `clone_val` which clones the
/// underlying CFFI handle.
///
#[repr(C)]
pub struct Value(Handle);

// By default, Values would not be marked Send because of the raw pointer they hold.
// Because the handle is opaque and can't be cloned, we can safely implement Send.
unsafe impl Send for Value {}
unsafe impl Sync for Value {}

impl Drop for Value {
  fn drop(&mut self) {
    enqueue_drop_handle(self.0);
  }
}

impl Value {
  ///
  /// An escape hatch to allow for cloning a Value without cloning its handle. You should generally
  /// not do this unless you are certain the input Value has been mem::forgotten (otherwise it
  /// will be `Drop`ed twice).
  ///
  pub unsafe fn clone_without_handle(&self) -> Value {
    Value(self.0)
  }
}

///
/// Implemented by calling back to python to clone the underlying Handle.
///
impl Clone for Value {
  fn clone(&self) -> Value {
    externs::clone_val(self)
  }
}

impl fmt::Debug for Value {
  fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
    write!(f, "{}", externs::val_to_str(&self))
  }
}

#[derive(Debug, Clone)]
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
#[derive(Clone, Eq, PartialEq, Ord, PartialOrd)]
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
