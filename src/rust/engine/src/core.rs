// TODO: representing python types?
pub type TypeId = u64;

// The name of a field.
pub type Field = Key;

// On the python side this is string->string; but to allow for equality checks
// without a roundtrip to python, we keep them encoded here.
pub type Variants = Vec<(Key, Key)>;

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Key {
  // The 64 byte digest is split in two because the derived traits above are only
  // implemented for arrays up to length 32: see
  //   https://doc.rust-lang.org/std/primitive.array.html
  digest_upper: [u8;32],
  digest_lower: [u8;32],
  type_id: TypeId,
}

impl Key {
  pub fn type_id(&self) -> TypeId {
    self.type_id
  }
}
