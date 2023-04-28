python_requirement(name="myst-parser", requirements=["myst-parser"], resolve="sphinx")
python_requirement(
    name="sphinx", requirements=["sphinx"], resolve="sphinx", dependencies=[":myst-parser"]
)

python_sources(name="conf", sources=["markdown/conf.py"], resolve="sphinx")
files(
    name="inputs",
    sources=[
        # "_static/**/*", "_templates/**/*",
        "markdown/**/*.md"
    ],
)

adhoc_tool(
    name="build-html",
    runnable=":sphinx",
    args=["-M", "html", "markdown", "_build"],
    execution_dependencies=[":inputs", ":conf"],
    output_directories=["_build"],
)
