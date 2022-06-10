---
title: "py-constraints"
slug: "reference-py-constraints"
hidden: false
createdAt: "2022-06-02T21:09:27.171Z"
updatedAt: "2022-06-02T21:09:27.493Z"
---
```
./pants py-constraints [args]
```
Determine what Python interpreter constraints are used by files/targets.

Backend: <span style="color: purple"><code>pants.backend.python.mixed_interpreter_constraints</code></span>
Config section: <span style="color: purple"><code>[py-constraints]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>output_file</code></h3>
  <code>--py-constraints-output-file=&lt;path&gt;</code><br>
  <code>PANTS_PY_CONSTRAINTS_OUTPUT_FILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Output the goal's stdout to this file. If unspecified, outputs to stdout.
</div>
<br>

<div style="color: purple">
  <h3><code>summary</code></h3>
  <code>--[no-]py-constraints-summary</code><br>
  <code>PANTS_PY_CONSTRAINTS_SUMMARY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Output a CSV summary of interpreter constraints for your whole repository. The headers are `Target`, `Constraints`, `Transitive Constraints`, `# Dependencies`, and `# Dependees`.

This information can be useful when prioritizing a migration from one Python version to another (e.g. to Python 3). Use `# Dependencies` and `# Dependees` to help prioritize which targets are easiest to port (low # dependencies) and highest impact to port (high # dependees).

Use a tool like Pandas or Excel to process the CSV. Use the option `--py-constraints-output-file=summary.csv` to write directly to a file.
</div>
<br>


## Advanced options

None

## Deprecated options

None


## Related subsystems
[python](reference-python)