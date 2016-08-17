use core::{Key, TypeId, Field};

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Select {
  pub product: TypeId,
  pub optional: bool,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectVariant {
  pub product: TypeId,
  pub variant_key: String,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectDependencies {
  pub product: TypeId,
  pub dep_product: TypeId,
  pub field: Field,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectProjection {
  pub product: TypeId,
  pub projected_subject: TypeId,
  pub field: Field,
  pub input_product: TypeId,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectLiteral {
  pub subject: Key,
  pub product: TypeId,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum Selector {
  Select(Select),
  SelectVariant(SelectVariant),
  SelectDependencies(SelectDependencies),
  SelectProjection(SelectProjection),
  SelectLiteral(SelectLiteral),
}

impl Selector {
  pub fn optional(&self) -> bool {
    match self {
      &Selector::Select(ref select) => select.optional,
      _ => false,
    }
  }
}
