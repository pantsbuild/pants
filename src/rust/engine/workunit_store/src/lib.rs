use parking_lot::Mutex;

pub struct WorkUnit {
    pub name: String,
    pub start_timestamp: f64,
    pub end_timestamp: f64,
    pub span_id: String,
}

pub trait WorkUnitStore {
    fn should_record_zipkin_spans(&self) -> bool;
    fn get_workunits(&self) -> &Mutex<Vec<WorkUnit>>;
    fn add_workunit(&self, workunit: WorkUnit);
}
