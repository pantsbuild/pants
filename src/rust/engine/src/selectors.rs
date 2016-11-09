use core::{Field, Function, Key, TypeConstraint, TypeId};

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Select {
  pub product: TypeConstraint,
  pub variant_key: Option<String>,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectDependencies {
  pub product: TypeConstraint,
  pub dep_product: TypeConstraint,
  pub field: Field,
  pub transitive: bool,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectProjection {
  pub product: TypeConstraint,
  // TODO: This should in theory be a TypeConstraint, but because the `project` operation
  // needs to construct an instance of the type if the result doesn't match, we use
  // a concrete type here.
  pub projected_subject: TypeId,
  pub field: Field,
  pub input_product: TypeConstraint,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectLiteral {
  pub subject: Key,
  pub product: TypeConstraint,
}

// NB: The `Task` selector is not user facing, and is provided for symmetry.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Task {
  pub product: TypeConstraint,
  pub clause: Vec<Selector>,
  pub func: Function,
  pub cacheable: bool,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum Selector {
  Select(Select),
  SelectDependencies(SelectDependencies),
  SelectProjection(SelectProjection),
  SelectLiteral(SelectLiteral),
  Task(Task),
}

impl Selector {
  pub fn select(product: TypeConstraint) -> Selector {
    Selector::Select(
      Select {
        product: product,
        variant_key: None,
      }
    )
  }

  pub fn product(&self) -> &TypeConstraint {
    match self {
      &Selector::Select(ref s) => &s.product,
      &Selector::SelectLiteral(ref s) => &s.product,
      &Selector::SelectDependencies(ref s) => &s.product,
      &Selector::SelectProjection(ref s) => &s.product,
      &Selector::Task(ref t) => &t.product,
    }
  }
}
