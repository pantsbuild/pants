use fnv::FnvHasher;
use libc;

use std::hash;
use std::ptr;

pub type FNV = hash::BuildHasherDefault<FnvHasher>;

// The type of a python object (which itself has a type, but which is not
// represented by a Key, because that would result in a recursive structure.)
pub type TypeId = Id;

// An identifier for a python function.
pub type Function = Id;

// The name of a field.
// TODO: Change to just a Id... we don't need type information here.
pub type Field = Key;

// On the python side this is string->string; but to allow for equality checks
// without a roundtrip to python, we keep them encoded here.
pub type Variants = Vec<(Field, Field)>;

// NB: These structs are fairly small, so we allow copying them by default.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Id {
  key: u64,
}

#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct Key {
  key: Id,
  value: Value,
  type_id: TypeId,
}

impl Eq for Key {}

impl PartialEq for Key {
  fn eq(&self, other: &Key) -> bool {
    self.key == other.key
  }
}

impl hash::Hash for Key {
  fn hash<H: hash::Hasher>(&self, state: &mut H) {
    self.key.hash(state);
  }
}

impl Key {
  pub fn empty() -> Key {
    Key {
      key: Id {
        key: 0
      },
      value: Value::empty(),
      type_id: TypeId {
        key: 0
      },
    }
  }

  pub fn key(&self) -> &Id {
    &self.key
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
#[derive(Clone, Copy, Debug)]
pub struct Value {
  handle: *const libc::c_void,
  type_id: TypeId,
}

impl Value {
  pub fn empty() -> Value {
    Value {
      handle: ptr::null() as *const libc::c_void,
      type_id: TypeId {
        key: 0
      },
    }
  }

  pub fn type_id(&self) -> &TypeId {
    &self.type_id
  }
}
