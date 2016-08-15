use core::{Key, TypeId};

#[derive(Debug, Eq, Hash, PartialEq)]
pub struct Select {
  product: TypeId,
  optional: bool,
}

#[derive(Debug, Eq, Hash, PartialEq)]
pub struct SelectVariant {
  product: TypeId,
  variant_key: String,
}

#[derive(Debug, Eq, Hash, PartialEq)]
pub struct SelectDependencies {
  product: TypeId,
  dep_product: TypeId,
  field: String,
}

#[derive(Debug, Eq, Hash, PartialEq)]
pub struct SelectProjection {
  product: TypeId,
  projected_subject: TypeId,
  fields: Vec<String>,
  input_product: TypeId,
}

#[derive(Debug, Eq, Hash, PartialEq)]
pub struct SelectLiteral {
  pub subject: Key,
  product: TypeId,
}

#[derive(Debug, Eq, Hash, PartialEq)]
pub enum Selector {
  Select(Select),
  SelectVariant(SelectVariant),
  SelectDependencies(SelectDependencies),
  SelectProjection(SelectProjection),
  SelectLiteral(SelectLiteral),
}

impl Selector {
  pub fn optional(&self) -> bool {
    match *self {
      Selector::Select(select) => select.optional,
      _ => false,
    }
  }
}
