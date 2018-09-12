// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::RwLock;

use futures::future::IntoFuture;
use futures_cpupool::{self, CpuFuture, CpuPool};

///
/// A wrapper around a CpuPool, to add the ability to drop the pool before forking,
/// and then lazily re-initialize it in a new process.
///
/// When a process forks, the kernel clones only the thread that called fork: all other
/// threads are effectively destroyed. If a CpuPool has live threads during a fork, it
/// will not be able to perform any work or be dropped cleanly (it will hang instead).
/// It's thus necessary to drop the pool before forking, and to re-create it after forking.
///
pub struct ResettablePool {
  name_prefix: String,
  pool: RwLock<Option<CpuPool>>,
}

impl ResettablePool {
  pub fn new(name_prefix: String) -> ResettablePool {
    ResettablePool {
      name_prefix: name_prefix.clone(),
      pool: RwLock::new(Some(Self::new_pool(name_prefix))),
    }
  }

  fn new_pool(name_prefix: String) -> CpuPool {
    futures_cpupool::Builder::new()
      .name_prefix(name_prefix)
      .create()
  }

  ///
  /// Delegates to `CpuPool::spawn_fn`, and shares its signature.
  /// http://alexcrichton.com/futures-rs/futures_cpupool/struct.CpuPool.html#method.spawn_fn
  ///
  pub fn spawn_fn<F, R>(&self, f: F) -> CpuFuture<R::Item, R::Error>
  where
    F: FnOnce() -> R + Send + 'static,
    R: IntoFuture + 'static,
    R::Future: Send + 'static,
    R::Item: Send + 'static,
    R::Error: Send + 'static,
  {
    let pool_opt = self.pool.read().unwrap();
    let pool = pool_opt
      .as_ref()
      .unwrap_or_else(|| panic!("A CpuPool cannot be used inside the fork context."));
    pool.spawn_fn(f)
  }

  ///
  /// Run a function while the pool is shut down, and restore the pool after it completes.
  ///
  pub fn with_shutdown<F, T>(&self, f: F) -> T
  where
    F: FnOnce() -> T,
  {
    let mut pool = self.pool.write().unwrap();
    *pool = None;
    let t = f();
    *pool = Some(Self::new_pool(self.name_prefix.clone()));
    t
  }
}
