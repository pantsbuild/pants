python_requirements(
    name="reqs",
    source="requirements.in",
    resolve="test",
)

python_test(
    name="test",
    source="test_extras_bug.py",
    resolve="test",
    # google-cloud-speech==2.21.0 depends on google-api-core[grpc] (extras chain)
    # google-cloud-storage depends on google-api-core (no extras)
    # Both paths hit google-api-core; bug: Pants may resolve it as non-extras,
    # skipping optional-dependencies.grpc and omitting grpcio from the PEX.
    dependencies=[":reqs#google-cloud-speech", ":reqs#google-cloud-storage"],
)
