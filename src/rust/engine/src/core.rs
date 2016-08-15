use std::hash::{Hash, Hasher};
use std::fmt;

pub type Digest = Vec<u8>;

// TODO: representing python types?
pub type TypeId = u64;

pub type Variants = Vec<(String,String)>;

#[derive(Debug, Eq, Hash, PartialEq)]
pub struct Key {
  digest: Digest,
  // TODO
  //value: *mut c_void,
}
