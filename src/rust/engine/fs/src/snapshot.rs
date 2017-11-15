use PathStat;
use hash::Fingerprint;
use std::fmt;

#[derive(Clone)]
pub struct Snapshot {
  pub fingerprint: Fingerprint,
  pub path_stats: Vec<PathStat>,
}

impl fmt::Debug for Snapshot {
  fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
    write!(
      f,
      "Snapshot({}, entries={})",
      self.fingerprint.to_hex(),
      self.path_stats.len()
    )
  }
}
