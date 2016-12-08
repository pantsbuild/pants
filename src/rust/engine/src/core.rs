use fnv::FnvHasher;

use std::collections::{HashMap, VecDeque};
use std::hash;
use std::marker::Sync;
use std::ops::Drop;
use std::os::raw;
use std::ptr;
use std::rc::Rc;
use std::sync::Mutex;

pub type FNV = hash::BuildHasherDefault<FnvHasher>;

type Handle = *const raw::c_void;

/**
 * A static queue of Handles which used to be owned by `Value`s. When a Value is dropped, its
 * Handle is added to this queue. Some thread with access to the ExternContext should periodically
 * consume this queue to drop the relevant handles on the python side.
 *
 * This queue avoids giving every `Value` a reference to the ExternContext, which would allow them
 * to drop themselves directly, but would increase their size.
 */
lazy_static! {
  pub static ref DROPPED_HANDLES: Mutex<VecDeque<Value>> = Mutex::new(VecDeque::new());
}

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
#[derive(Clone, Debug, Default, Eq, Hash, PartialEq)]
pub struct Field(pub Key);

#[repr(C)]
#[derive(Clone, Debug, Default)]
pub struct Key {
  id: Id,
  value: Rc<Value>,
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

/**
 * Represents a handle to a python object, explicitly without equality or hashing. Whenever
 * the equality/identity of a Value matters, a Key should be computed for it and used instead.
 */
#[repr(C)]
#[derive(Clone, Debug)]
pub struct Value {
  handle: *const raw::c_void,
  type_id: TypeId,
}

unsafe impl Send for Value { }

unsafe impl Sync for Value { }

impl Drop for Value {
  fn drop(&mut self) {
    DROPPED_HANDLES.lock().unwrap().push_back(self);
  }
}

impl Value {
  pub fn type_id(&self) -> &TypeId {
    &self.type_id
  }
}

impl Default for Value {
  fn default() -> Self {
    Value {
      handle: ptr::null() as *const raw::c_void,
      type_id: TypeId(0),
    }
  }
}
