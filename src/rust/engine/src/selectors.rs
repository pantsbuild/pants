use core::{Field, Function, Key, TypeId};

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Select {
  pub product: TypeId,
  pub variant_key: Option<Key>,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectDependencies {
  pub product: TypeId,
  pub dep_product: TypeId,
  pub field: Field,
  pub traversal: bool,
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

// NB: The `Task` selector is not user facing, and is provided for symmetry.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Task {
  pub product: TypeId,
  pub clause: Vec<Selector>,
  pub func: Function,
  pub cacheable: bool,
}

impl Task {
  pub fn cacheable(&self) -> bool {
    self.cacheable
  }

  pub fn func(&self) -> &Function {
    &self.func
  }

  pub fn clause(&self) -> &Vec<Selector> {
    &self.clause
  }
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
  pub fn select(product: TypeId) -> Selector {
    Selector::Select( 
      Select {
        product: product,
        variant_key: None,
      }
    )
  }

  pub fn product(&self) -> &TypeId {
    match self {
      &Selector::Select(ref s) => &s.product,
      &Selector::SelectLiteral(ref s) => &s.product,
      &Selector::SelectDependencies(ref s) => &s.product,
      &Selector::SelectProjection(ref s) => &s.product,
      &Selector::Task(ref t) => &t.product,
    }
  }
}
