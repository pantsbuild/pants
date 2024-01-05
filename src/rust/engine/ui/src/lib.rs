// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use futures::future::BoxFuture;
use futures::future::FutureExt;
use instance::Instance;
use std::future::Future;
use std::time::Duration;
use task_executor::Executor;
use workunit_store::WorkunitStore;
mod instance;

#[derive(Clone, Copy, Debug)]
pub enum LogStreamingLines {
    Exact(usize),
    Auto,
}

#[derive(Clone, Copy, Debug)]
pub enum LogStreamingTopn {
    Exact(usize),
    Auto,
}

pub struct ConsoleUI {
    workunit_store: WorkunitStore,
    local_parallelism: usize,
    ui_use_prodash: bool,
    // While the UI is running, there will be an Instance present.
    instance: Option<Instance>,

    log_streaming: bool,
    log_streaming_lines: LogStreamingLines,
    log_streaming_topn: LogStreamingTopn,
}

impl ConsoleUI {
    pub fn new(
        workunit_store: WorkunitStore,
        local_parallelism: usize,
        log_streaming: bool,
        log_streaming_lines: LogStreamingLines,
        log_streaming_topn: LogStreamingTopn,
        ui_use_prodash: bool,
    ) -> ConsoleUI {
        ConsoleUI {
            workunit_store,
            local_parallelism,
            ui_use_prodash,
            log_streaming,
            log_streaming_lines,
            log_streaming_topn,

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
        let mut log_retriver =
            |span_id, line_count| self.workunit_store.read_log_lines(span_id, line_count);
        instance.render(&heavy_hitters, &mut log_retriver);
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
            self.log_streaming,
            self.log_streaming_lines,
            self.log_streaming_topn,
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
