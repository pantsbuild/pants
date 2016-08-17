use core::{Key, TypeId, Field};

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Select {
  pub product: TypeId,
  pub optional: bool,
  pub variant_key: Option<Key>,
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
  SelectDependencies(SelectDependencies),
  SelectProjection(SelectProjection),
  SelectLiteral(SelectLiteral),
}

impl Selector {
  pub fn select(product: TypeId) -> Selector {
    Selector::Select(
      Select {
        product: product,
        optional: false,
        variant_key: None,
      }
    )
  }

  pub fn optional(&self) -> bool {
    match self {
      &Selector::Select(ref select) => select.optional,
      _ => false,
    }
  }
}
