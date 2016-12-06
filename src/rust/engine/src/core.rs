use fnv::FnvHasher;
use libc;

use std::collections::HashMap;
use std::hash;
use std::ptr;

pub type FNV = hash::BuildHasherDefault<FnvHasher>;

/**
 * Variants represent a string->string map. For hashability purposes, they're stored
 * as sorted string tuples.
 */
#[repr(C)]
#[derive(Clone, Debug, Default, Eq, Hash, PartialEq)]
pub struct Variants(pub Vec<(String, String)>);

impl Variants {

  /**
   * Merges right over self (by key, and then sorted by key).
   *
   * TODO: Unused: see https://github.com/pantsbuild/pants/issues/4020
   */
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
    self.0.iter()
      .find(|&&(ref k, _)| k == key)
      .map(|&(_, ref v)| v.as_str())
  }
}

pub type Id = u64;

// The type of a python object (which itself has a type, but which is not represented
// by a Key, because that would result in a infinitely recursive structure.)
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, Hash, PartialEq)]
pub struct TypeId(pub Id);

// A type constraint, which a TypeId may or may-not satisfy.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, Hash, PartialEq)]
pub struct TypeConstraint(pub Id);

// An identifier for a python function.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, Hash, PartialEq)]
pub struct Function(pub Id);

// The name of a field.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, Hash, PartialEq)]
pub struct Field(pub Key);

#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct Key {
  id: Id,
  value: Value,
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
  pub fn id(&self) -> Id {
    self.id
  }

  pub fn value(&self) -> &Value {
    &self.value
  }

  pub fn type_id(&self) -> &TypeId {
    &self.type_id
  }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct RunnableComplete {
  value: Value,
  is_throw: bool,
}

impl RunnableComplete {
  pub fn value(&self) -> &Value {
    &self.value
  }

  pub fn is_throw(&self) -> bool {
    self.is_throw
  }
}

/**
 * Represents a handle to a python object, explicitly without equality or hashing. Whenever
 * the equality/identity of a Value matters, a Key should be computed for it and used instead.
 */
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct Value {
  handle: *const libc::c_void,
  type_id: TypeId,
}

impl Value {
  pub fn type_id(&self) -> &TypeId {
    &self.type_id
  }
}

impl Default for Value {
  fn default() -> Self {
    Value {
      handle: ptr::null() as *const libc::c_void,
      type_id: TypeId(0),
    }
  }
}
