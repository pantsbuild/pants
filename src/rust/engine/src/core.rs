pub type Digest = [u8;64];

// TODO: representing python types?
pub type TypeId = u64;

pub struct Key {
  digest: Digest,
  // TODO
  //value: *mut c_void,
}

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
