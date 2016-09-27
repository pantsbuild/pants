use fnv::FnvHasher;
use libc;

use std::fmt;
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
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Key {
  key: Id,
  type_id: TypeId,
}

impl Key {
  pub fn empty() -> Key {
    Key {
      key: Id {
        key: 0
      },
      type_id: TypeId {
        key: 0
      },
    }
  }

  pub fn key(&self) -> &Id {
    &self.key
  }

  pub fn type_id(&self) -> &TypeId {
    &self.type_id
  }
}

/**
 * Represents a handle to a python object, explicitly without equality or hashing. Whenever
 * the equality/identity of a Value matters, a Key should be computed for it and used instead.
 *
 * We manually implement Copy/Clone, because despite being opaque, c_void is not Clone/Copy for
 * some reason.
 */
#[repr(C)]
pub struct Value {
  handle: libc::c_void,
  type_id: TypeId,
}

impl Clone for Value {
  fn clone(&self) -> Value {
    Value {
      handle: self.handle,
      type_id: self.type_id
    }
  }
}

impl fmt::Debug for Value {
  fn fmt(&self, fmtr: &mut fmt::Formatter) -> Result<(), fmt::Error> {
    fmtr.write_fmt(format_args!("Value {{ type_id: {:?} }}", self.type_id))
  }
}

impl Value {
  pub fn empty() -> Value {
    Value {
      handle: ptr::null(),
      type_id: TypeId {
        key: 0
      },
    }
  }

  pub fn type_id(&self) -> &TypeId {
    &self.type_id
  }
}
