pub type Digest = Vec<u8>;

// TODO: representing python types?
pub type TypeId = u64;

// The name of a field.
pub type Field = Key;

// On the python side this is string->string; but to allow for equality checks
// without a roundtrip to python, we keep them encoded here.
pub type Variants = Vec<(Key, Key)>;

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Key {
  digest: Digest,
  type_id: TypeId,
  // TODO
  //value: *mut c_void,
}

impl Key {
  pub fn type_id(&self) -> TypeId {
    self.type_id
  }
}
