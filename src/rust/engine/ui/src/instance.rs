// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use futures::future::BoxFuture;
use std::collections::HashMap;
use std::collections::HashSet;
use std::time::SystemTime;
use task_executor::Executor;
use terminal_size::terminal_size_using_fd;
use workunit_store::SpanId;

mod indicatif;
mod prodash;

use crate::LogStreamingLines;
use crate::LogStreamingTopn;

use self::indicatif::IndicatifInstance;
use self::prodash::ProdashInstance;

/// The state for one run of the ConsoleUI.
pub(super) enum Instance {
    Indicatif(IndicatifInstance),
    Prodash(ProdashInstance),
}

enum TaskState {
    New,
    Update,
    Remove,
}

impl Instance {
    ///
    /// Setup an Instance of the UI renderer.
    ///
    /// NB: This method must be very careful to avoid logging. Between the point where we have taken
    /// exclusive access to the Console and when the UI has actually been initialized, attempts to
    /// log from this method would deadlock (by causing the method to wait for _itself_ to finish).
    ///
    pub fn new(
        ui_use_prodash: bool,
        log_streaming: bool,
        log_streaming_lines: LogStreamingLines,
        log_streaming_topn: LogStreamingTopn,
        local_parallelism: usize,
        executor: Executor,
    ) -> Result<Instance, String> {
        let stderr_fd = stdio::get_destination().stderr_as_raw_fd()?;
        let (terminal_width, terminal_height) = terminal_size_using_fd(stderr_fd)
            .map(|terminal_dimensions| (terminal_dimensions.0 .0, terminal_dimensions.1 .0 - 1))
            .unwrap_or((50, local_parallelism.try_into().unwrap()));

        if ui_use_prodash {
            let instance =
                prodash::ProdashInstance::new(executor.clone(), terminal_width, terminal_height)?;
            Ok(Instance::Prodash(instance))
        } else {
            let instance = indicatif::IndicatifInstance::new(
                local_parallelism,
                terminal_width,
                terminal_height,
                log_streaming,
                log_streaming_lines,
                log_streaming_topn,
            )?;

            Ok(Instance::Indicatif(instance))
        }
    }

    ///
    /// Update the rendering with new data.
    ///
    pub fn render(
        &mut self,
        heavy_hitters: &HashMap<SpanId, (String, SystemTime)>,
        log_retriever: &mut dyn FnMut(SpanId, usize) -> Option<Vec<u8>>,
    ) {
        match self {
            Instance::Indicatif(indicatif) => indicatif.render(heavy_hitters, log_retriever),
            Instance::Prodash(prodash) => prodash.render(heavy_hitters),
        };
    }

    ///
    /// Destroy the instance, releasing any data.
    ///
    pub fn teardown(self) -> BoxFuture<'static, ()> {
        match self {
            Instance::Indicatif(indicatif) => indicatif.teardown(),
            Instance::Prodash(prodash) => prodash.teardown(),
        }
    }
}

fn classify_tasks(
    heavy_hitters: &HashMap<SpanId, (String, SystemTime)>,
    mut current_ids: HashSet<SpanId>,
    handler: &mut dyn FnMut(SpanId, TaskState),
) {
    for span_id in heavy_hitters.keys() {
        let update = current_ids.remove(span_id);
        let task_state = if update {
            TaskState::Update
        } else {
            TaskState::New
        };

        handler(*span_id, task_state)
    }

    for span_id in current_ids {
        handler(span_id, TaskState::Remove);
    }
}
