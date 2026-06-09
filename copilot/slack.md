Yi Cheng  [12:56 AM]

Symptom is that we are seeing out of disk issue on jenkins when building a really small pex with errors like
```
 Downloaded nvidia-cufft
   Building pyspark==3.5.5
 Downloaded nvidia-cudnn-cu13
 Downloaded nvidia-cublas
  × Failed to download `torch==2.12.0`
  ├─▶ Failed to extract archive:
  │   torch-2.12.0-cp310-cp310-manylinux_2_28_x86_64.whl
  ├─▶ I/O operation failed during extraction
  ╰─▶ failed to write to file
      `/mnt/data/agent/cache/tmp/pants-sandbox-0Qzbb9/.cache/uv_cache/.tmphW4bpP/torch/lib/libtorch_cpu.so`:
      No space left on device (os error 28)
  help: `torch` (v2.12.0) was included because
        `pants-lockfile-for-python-default` (v0.0.0) depends on `torch`
```

but that particular pex only has 1-2 small 3rdparty deps transitively.

So I suspected that pants with resolver=uv may be instantiating the entire resolve, and claude seems concur:
With resolver = "pex" (main branch): When building a PEX for a PexRequirements target (your 2-dep script), Pants calls pex with [*req_strings, "--lock", lockfile_path] (line 700-709). Pex reads the lockfile and only downloads/installs requests, metatron, and their
 transitive deps — it subsets the lockfile. Never touches torch, CUDA, etc.

```
 With resolver = "uv" (your branch): When building the same target, Pants hits line 679-682 and punts to create_venv_repository_from_uv_lockfile, which runs uv sync --frozen --all-extras on the entire default_universe.lock. Every package in the resolve — torch (507
 MB), nvidia-*, ... — gets downloaded and extracted. This exhausts the CI agent's disk at torch.

  The comment in the code at line 618-620 confirms this is a known awkward gap:

  ▎ "The caller will need to set the argv. This is slightly awkward, and due to uv support being tacked on later."

  The design intent is that the full-resolve venv is a shared cached package repository (one per resolve) that amortizes cost across many targets. But for cold CI agents with no persistent venv_cache, it forces a multi-GB download just to build a 2-dep PEX.

  Bottom line: This is a known capability regression in uv support vs. pex for cold-cache builds. The pex resolver subsets the lockfile per target; the uv resolver always materializes the full resolve first. The separate-resolve fix I described earlier is the right
  workaround until upstream Pants adds selective uv sync --package support for individual PEX builds.
```


Yi Cheng  [12:58 AM]
cc @Benjy, may not be a blocker for some.
for us, we are ML heavy (large 3rdparty deps), so had to roll back to resolver=pex


Benjy Weinberger  [2:41 AM]
Yes, currently, by design, uv syncs the entire lockfile to a venv, and pex then treats that venv as a repository from which to consume the required subset of requirements.
[2:42 AM]Just to confirm: what's killing you is uv creating that venv? i.e., not pex accidentally trying to consume more requirements than it needs


Yi Cheng  [2:43 AM]
that's correct. the failure is still at uv (creating the venv) phase.
[2:43 AM]thanks for clarifying!
[2:44 AM]not blocking for the release since this may not be a problem for other users.


Benjy Weinberger  [2:45 AM]
We could use uv's `--only-group` option, and generate an ephemeral dependency group for just the immediate deps you care about
