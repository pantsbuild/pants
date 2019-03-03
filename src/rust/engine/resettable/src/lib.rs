// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::single_match_else,
  clippy::unseparated_literal_suffix,
  clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(
  clippy::new_without_default,
  clippy::new_without_default,
  clippy::new_ret_no_self
)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

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
  make: Arc<dyn Fn() -> T>,
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
    Resettable {
      val: Arc::new(RwLock::new(None)),
      make: Arc::new(make),
    }
  }

  ///
  /// Execute f with the value in the Resettable.
  /// May lazily initialize the value in the Resettable.
  ///
  /// TODO Explore the use of parking_lot::RWLock::upgradable_read
  /// to avoid reacquiring the lock for initialization.
  /// This can be used if we are sure that a deadlock won't happen
  /// when two readers are trying to upgrade at the same time.
  ///
  pub fn with<O, F: FnOnce(&T) -> O>(&self, f: F) -> O {
    {
      let val_opt = self.val.read();
      if let Some(val) = val_opt.as_ref() {
        return f(val);
      }
    }
    let mut val_write_opt = self.val.write();
    if val_write_opt.as_ref().is_none() {
      *val_write_opt = Some((self.make)())
    }
    f(val_write_opt.as_ref().unwrap())
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
    f()
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
    self.with(T::clone)
  }
}
