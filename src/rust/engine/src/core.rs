use fnv::FnvHasher;
use libc;

use std::hash;
use std::ptr;

pub type FNV = hash::BuildHasherDefault<FnvHasher>;

// On the python side this is string->string; but to allow for equality checks
// without a roundtrip to python, we keep them encoded here.
pub type Variants = Vec<(Key, Key)>;

pub type Id = u64;

// The type of a python object (which itself has a type, but which is not
// represented by a Key, because that would result in a recursive structure.)
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct TypeId(pub Id);

// A type constraint, which a TypeId may or may-not satisfy.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct TypeConstraint(pub Id);

// An identifier for a python function.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Function(pub Id);

// The name of a field.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Field(pub Key);

#[repr(C)]
#[derive(Clone, Copy, Debug)]
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
  pub fn empty() -> Key {
    Key {
      id: 0,
      value: Value::empty(),
      type_id: TypeId(0),
    }
  }

  pub fn id(&self) -> &Id {
    &self.id
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
      type_id: TypeId(0),
    }
  }

  pub fn type_id(&self) -> &TypeId {
    &self.type_id
  }
}
