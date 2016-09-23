use fnv::FnvHasher;

use std::hash;

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
