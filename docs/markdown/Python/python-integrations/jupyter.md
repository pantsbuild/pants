---
title: "Jupyter"
slug: "jupyter"
excerpt: "A Jupyter plugin to load Pants targets into Jupyter Notebooks."
hidden: false
createdAt: "2021-03-25T20:26:11.111Z"
---
The [pants-jupyter-plugin](https://github.com/pantsbuild/pants-jupyter-plugin/) project provides a Jupyter plugin that can be used to load Pants targets directly into a notebook.

Installation
------------

Jupyter plugins are typically installed using `pip` directly alongside Jupyter (Lab) itself.

If you don't already have Jupyter set up somewhere, create a virtualenv for it, and then install and start it by running:

```shell
# Install jupyter and the plugin (NB: please use a virtualenv!)
pip install jupyterlab pants-jupyter-plugin
# Launch JupyterLab, which will open a browser window for notebook editing.
jupyter lab
```

Usage
-----

For instructions on using the plugin, see its [README](https://github.com/pantsbuild/pants-jupyter-plugin/blob/main/README.md).

An example session that loads a target from the example-python repository might look like:

![](https://files.readme.io/9f7ca19-jupyter-session.png "jupyter-session.png")
