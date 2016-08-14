pub type Digest = [u8;64];

// TODO: representing python types?
pub type TypeId = u64;

pub struct Key {
  digest: Digest,
  // TODO
  //value: *mut c_void,
}
