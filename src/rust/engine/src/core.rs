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

#[derive(Debug, Eq, Hash, PartialEq)]
pub enum Selector {
  Select {
    product: TypeId,
    optional: bool,
  },
  SelectVariant {
    product: TypeId,
    variant_key: String,
  },
  SelectDependencies {
    product: TypeId,
    dep_product: TypeId,
    field: String,
  },
  SelectProjection {
    product: TypeId,
    projected_subject: TypeId,
    fields: Vec<String>,
    input_product: TypeId,
  },
  SelectLiteral {
    subject: Key,
    product: TypeId,
  },
}
