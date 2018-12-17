// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![cfg_attr(
  feature = "cargo-clippy",
  deny(
    clippy,
    default_trait_access,
    expl_impl_clone_on_copy,
    if_not_else,
    needless_continue,
    single_match_else,
    unseparated_literal_suffix,
    used_underscore_binding
  )
)]
// It is often more clear to show that nothing is being moved.
#![cfg_attr(feature = "cargo-clippy", allow(match_ref_pats))]
// Subjective style.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(len_without_is_empty, redundant_field_names)
)]
// Default isn't as big a deal as people seem to think it is.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(new_without_default, new_without_default_derive)
)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![cfg_attr(feature = "cargo-clippy", allow(mutex_atomic))]

extern crate parking_lot;

use std::sync::Arc;

use parking_lot::RwLock;

///
/// Resettable is a lazily computed value which can be reset, so that it can be lazily computed
/// again next time it is needed.
///
/// This is useful because we fork without execing a lot in the engine, and before doing so, we need
/// to reset any references which hide background threads, so that forked processes don't inherit
/// pointers to threads from the parent process which will not exist in the forked process.
///
pub struct Resettable<T> {
  val: Arc<RwLock<Option<T>>>,
  make: Arc<Fn() -> T>,
}

// Sadly we need to manualy implement Clone because of https://github.com/rust-lang/rust/issues/26925
impl<T> Clone for Resettable<T> {
  fn clone(&self) -> Self {
    Resettable {
      val: self.val.clone(),
      make: self.make.clone(),
    }
  }
}

unsafe impl<T> Send for Resettable<T> {}
unsafe impl<T> Sync for Resettable<T> {}

impl<T> Resettable<T>
where
  T: Send + Sync,
{
  pub fn new<F: Fn() -> T + 'static>(make: F) -> Resettable<T> {
    let val = (make)();
    Resettable {
      val: Arc::new(RwLock::new(Some(val))),
      make: Arc::new(make),
    }
  }

  pub fn with<O, F: FnOnce(&T) -> O>(&self, f: F) -> O {
    let val_opt = self.val.read();
    let val = val_opt
      .as_ref()
      .unwrap_or_else(|| panic!("A Resettable value cannot be used while it is shutdown."));
    f(val)
  }

  ///
  /// Run a function while the Resettable resource is cleared, and then recreate it afterward.
  ///
  pub fn with_reset<F, O>(&self, f: F) -> O
  where
    F: FnOnce() -> O,
  {
    let mut val = self.val.write();
    *val = None;
    let t = f();
    *val = Some((self.make)());
    t
  }
}

impl<T> Resettable<T>
where
  T: Clone + Send + Sync,
{
  ///
  /// Callers should probably use `with` rather than `get`.
  /// Having an externalized `get` and using Clone like this is problematic: if there
  /// might be references/Clones of the field outside of the lock on the resource, then we can't
  /// be sure that dropping it will actually deallocate the resource.
  ///
  pub fn get(&self) -> T {
    let val_opt = self.val.read();
    let val = val_opt
      .as_ref()
      .unwrap_or_else(|| panic!("A Resettable value cannot be used while it is shutdown."));
    val.clone()
  }
}
