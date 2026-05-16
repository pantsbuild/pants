python_requirements(
    name="reqs",
    source="requirements.in",
    resolve="bug2",
)

python_test(
    name="test",
    source="test_transitive_extras_bug.py",
    resolve="bug2",
    # Only pkg-a is listed as a direct dep.
    # pkg-a → pkg-b (no extras at this edge)
    # pkg-b → pkg-c[myextra]  ← extras activated HERE (2nd level from BUILD dep)
    # pkg-c[myextra] → pkg-d  ← only via extra, no other path
    # If Pants/PEX drops [myextra] when traversing pkg-b's Requires-Dist,
    # pkg-d will be absent from requirements.pex.
    # pkg-e → pkg-c (no extras) creates a competing path to pkg-c.
    # If PEX satisfies pkg-c from pkg-e first (without [myextra]), it won't
    # re-activate extras when it later encounters pkg-b → pkg-c[myextra].
    dependencies=[":reqs#pkg-a", ":reqs#pkg-e"],
)
