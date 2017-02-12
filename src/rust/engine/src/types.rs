use core::{Function, TypeConstraint};

pub struct Types {
  pub construct_snapshot: Function,
  pub construct_file_content: Function,
  pub construct_files_content: Function,
  pub construct_path_stat: Function,
  pub construct_dir: Function,
  pub construct_file: Function,
  pub construct_link: Function,
  pub address: TypeConstraint,
  pub has_products: TypeConstraint,
  pub has_variants: TypeConstraint,
  pub path_globs: TypeConstraint,
  pub snapshot: TypeConstraint,
  pub files_content: TypeConstraint,
  pub read_link: TypeConstraint,
  pub directory_listing: TypeConstraint,
  pub dir: TypeConstraint,
  pub file: TypeConstraint,
  pub link: TypeConstraint,
}
