use core::TypeConstraint;

pub struct Types {
  pub address: TypeConstraint,
  pub has_products: TypeConstraint,
  pub has_variants: TypeConstraint,
  pub path_globs: TypeConstraint,
  pub snapshot: TypeConstraint,
  pub read_link: TypeConstraint,
  pub directory_listing: TypeConstraint,
}
