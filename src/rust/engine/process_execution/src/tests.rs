use crate::{ExecuteProcessRequest, PlatformConstraint, RelativePath};
use hashing::{Digest, Fingerprint};
use std::collections::hash_map::DefaultHasher;
use std::collections::{BTreeMap, BTreeSet};
use std::hash::{Hash, Hasher};
use std::time::Duration;

#[test]
fn execute_process_request_equality() {
  let execute_process_request_generator =
        |description: String, timeout: Duration, unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: hashing::Digest| ExecuteProcessRequest {
            argv: vec![],
            env: BTreeMap::new(),
            working_directory: None,
            input_files: hashing::EMPTY_DIGEST,
            output_files: BTreeSet::new(),
            output_directories: BTreeSet::new(),
            timeout,
            description,
            unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule,
            jdk_home: None,
            target_platform: PlatformConstraint::None,
            is_nailgunnable: false,
        };

  fn hash<Hashable: Hash>(hashable: &Hashable) -> u64 {
    let mut hasher = DefaultHasher::new();
    hashable.hash(&mut hasher);
    hasher.finish()
  }

  let a = execute_process_request_generator(
    "One thing".to_string(),
    Duration::new(0, 0),
    hashing::EMPTY_DIGEST,
  );
  let b = execute_process_request_generator(
    "Another".to_string(),
    Duration::new(0, 0),
    hashing::EMPTY_DIGEST,
  );
  let c = execute_process_request_generator(
    "One thing".to_string(),
    Duration::new(5, 0),
    hashing::EMPTY_DIGEST,
  );
  let d = execute_process_request_generator(
    "One thing".to_string(),
    Duration::new(0, 0),
    Digest(
      Fingerprint::from_hex_string(
        "0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff",
      )
      .unwrap(),
      1,
    ),
  );

  // ExecuteProcessRequest should derive a PartialEq and Hash that ignores the description
  assert!(a == b);
  assert!(hash(&a) == hash(&b));

  // `unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule` field should
  // be ignored for Hash
  assert!(a == d);
  assert!(hash(&a) == hash(&d));

  // but not other fields
  assert!(a != c);
  assert!(hash(&a) != hash(&c));
}

#[test]
fn relative_path_ok() {
  assert_eq!(Some("a"), RelativePath::new("a").unwrap().to_str());
  assert_eq!(Some("a"), RelativePath::new("./a").unwrap().to_str());
  assert_eq!(Some("a"), RelativePath::new("b/../a").unwrap().to_str());
  assert_eq!(
    Some("a/c"),
    RelativePath::new("b/../a/././c").unwrap().to_str()
  );
}

#[test]
fn relative_path_err() {
  assert!(RelativePath::new("../a").is_err());
  assert!(RelativePath::new("/a").is_err());
}
