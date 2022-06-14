---
title: "Jupyter"
slug: "jupyter"
excerpt: "A Jupyter plugin to load Pants targets into Jupyter Notebooks."
hidden: false
createdAt: "2021-03-25T20:26:11.111Z"
updatedAt: "2021-06-28T21:28:01.221Z"
---
The [pants-jupyter-plugin](https://github.com/pantsbuild/pants-jupyter-plugin/) project provides a Jupyter plugin that can be used to load Pants targets directly into a notebook.
[block:api-header]
{
  "title": "Installation"
}
[/block]
Jupyter plugins are typically installed using `pip` directly alongside Jupyter (Lab) itself.

If you don't already have Jupyter set up somewhere, create a virtualenv for it, and then install and start it by running:
[block:code]
{
  "codes": [
    {
      "code": "# Install jupyter and the plugin (NB: please use a virtualenv!)\npip install jupyterlab pants-jupyter-plugin\n# Launch JupyterLab, which will open a browser window for notebook editing.\njupyter lab",
      "language": "shell"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Usage"
}
[/block]
For instructions on using the plugin, see its [README](https://github.com/pantsbuild/pants-jupyter-plugin/blob/main/README.md).

An example session that loads a target from the example-python repository might look like:
[block:image]
{
  "images": [
    {
      "image": [
        "https://files.readme.io/9f7ca19-jupyter-session.png",
        "jupyter-session.png",
        1446,
        778,
        "#f1f2f3"
      ],
      "caption": ""
    }
  ]
}
[/block]