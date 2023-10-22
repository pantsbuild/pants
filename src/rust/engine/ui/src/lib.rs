// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
    clippy::all,
    clippy::default_trait_access,
    clippy::expl_impl_clone_on_copy,
    clippy::if_not_else,
    clippy::needless_continue,
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
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use futures::future::BoxFuture;
use futures::future::FutureExt;
use instance::Instance;
use std::future::Future;
use std::time::Duration;
use task_executor::Executor;
use workunit_store::WorkunitStore;
mod instance;

pub struct ConsoleUI {
    workunit_store: WorkunitStore,
    local_parallelism: usize,
    ui_use_prodash: bool,
    // While the UI is running, there will be an Instance present.
    instance: Option<Instance>,
}

impl ConsoleUI {
    pub fn new(
        workunit_store: WorkunitStore,
        local_parallelism: usize,
        ui_use_prodash: bool,
    ) -> ConsoleUI {
        ConsoleUI {
            workunit_store,
            local_parallelism,
            ui_use_prodash,
            instance: None,
        }
    }

    ///
    /// The number of times per-second that `Self::render` should be called.
    ///
    pub fn render_rate_hz() -> u8 {
        10
    }

    pub fn render_interval() -> Duration {
        Duration::from_millis(1000 / (Self::render_rate_hz() as u64))
    }

    pub async fn with_console_ui_disabled<T>(&mut self, f: impl Future<Output = T>) -> T {
        if self.instance.is_some() {
            self.teardown().await;
        }

        f.await
    }

    ///
    /// Updates all of items with new data from the WorkunitStore. For this
    /// method to have any effect, the `initialize` method must have been called first.
    ///
    /// *Technically this method does not do the "render"ing: rather, the background thread
    /// drives rendering, while this method feeds it new data.
    ///
    pub fn render(&mut self) {
        let Some(instance) = &mut self.instance else {
            return;
        };

        let heavy_hitters = self.workunit_store.heavy_hitters(self.local_parallelism);
        instance.render(&heavy_hitters)
    }

    ///
    /// If the ConsoleUI is not already running, starts it.
    ///
    /// Errors if a ConsoleUI is already running (which would likely indicate concurrent usage of a
    /// Session attached to a console).
    ///
    pub fn initialize(&mut self, executor: Executor) -> Result<(), String> {
        if self.instance.is_some() {
            return Err("A ConsoleUI cannot render multiple UIs concurrently.".to_string());
        }

        self.instance = Some(Instance::new(
            self.ui_use_prodash,
            self.local_parallelism,
            executor,
        )?);

        Ok(())
    }

    ///
    /// If the ConsoleUI is running, completes it.
    ///
    /// NB: This method returns a Future which will await teardown of the UI, which should be awaited
    /// outside of any UI locks.
    ///
    pub fn teardown(&mut self) -> BoxFuture<'static, ()> {
        if let Some(instance) = self.instance.take() {
            instance.teardown()
        } else {
            futures::future::ready(()).boxed()
        }
    }
}
