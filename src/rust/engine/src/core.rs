// The type of a python object (which itself has a type, but which is not
// represented by a Key, because that would result in a recursive structure.)
pub type TypeId = Digest;

// An identifier for a python function.
pub type Function = Digest;

// The name of a field.
pub type Field = Key;

// On the python side this is string->string; but to allow for equality checks
// without a roundtrip to python, we keep them encoded here.
pub type Variants = Vec<(Key, Key)>;

// NB: These structs are fairly small, so we allow copying them by default.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Digest {
  digest: [u8;32],
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Key {
  digest: Digest,
  type_id: TypeId,
}

impl Key {
  pub fn empty() -> Key {
    Key {
      digest: Digest {
        digest: [0;32]
      },
      type_id: TypeId {
        digest: [0;32]
      },
    }
  }

  pub fn type_id(&self) -> &TypeId {
    &self.type_id
  }
}
