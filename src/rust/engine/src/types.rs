use core::{Function, TypeConstraint, TypeId};

pub struct Types {
  pub construct_snapshot: Function,
  pub construct_snapshots: Function,
  pub construct_file_content: Function,
  pub construct_files_content: Function,
  pub construct_path_stat: Function,
  pub construct_dir: Function,
  pub construct_file: Function,
  pub construct_link: Function,
  pub construct_process_result: Function,
  pub address: TypeConstraint,
  pub has_products: TypeConstraint,
  pub has_variants: TypeConstraint,
  pub path_globs: TypeConstraint,
  pub snapshot: TypeConstraint,
  pub snapshots: TypeConstraint,
  pub files_content: TypeConstraint,
  pub dir: TypeConstraint,
  pub file: TypeConstraint,
  pub link: TypeConstraint,
  pub process_request: TypeConstraint,
  pub process_result: TypeConstraint,
  pub string: TypeId,
  pub bytes: TypeId,
}
