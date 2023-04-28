python_requirement(name="myst-parser", requirements=["myst-parser"], resolve="sphinx")
python_requirement(
    name="sphinx", requirements=["sphinx"], resolve="sphinx", dependencies=[":myst-parser"]
)

python_sources(name="conf", sources=["markdown/conf.py"], resolve="sphinx")
files(
    name="inputs",
    sources=[
        # "_static/**/*", "_templates/**/*",
        "markdown/**/*.md",
        "markdown/**/*.rst"
    ],
)

adhoc_tool(
    name="generated-pages",
    runnable="build-support/bin/generate_docs.py:py_scripts",
    args=["--no-prompt", "--skip-check-urls", "--output=markdown/generated"],
    output_directories=["markdown/generated"],
)

adhoc_tool(
    name="build-html",
    runnable=":sphinx",
    args=["-M", "html", "markdown", "_build"],
    execution_dependencies=[":inputs", ":conf", ":generated-pages"],
    output_directories=["_build/html"],
    root_output_directory="./_build/html",
    log_output=True,
)

archive(name="docs", files=[":build-html"], format="zip")
