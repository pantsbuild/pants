---
title: "Installing Pants"
slug: "installation"
hidden: false
createdAt: "2020-02-21T17:44:53.022Z"
updatedAt: "2022-07-12T00:00:00.000Z"
---

Most installations can use our one-step setup script to get a minimal version of Pants set up. If you need to make use of an advanced or non-standard setup, see our [manual installation](doc:manual-installation) page.

Using our one-step setup script
-------------------------------

Pants has a launch script (called `./pants`) that handles downloading, bootstrapping, and upgrading Pants, which you need to save at the root of your repository. 

Pants also needs a `pants.toml` file, where you will eventually add all of the configuration needed to run testing, linting, and formatting rules. For now, it just needs to specify the version of Pants that you want to use. 

To streamline this, we provide a script that will create a minimal `pants.toml` file specifying the latest released version of Pants, download, and run the `./pants` launch script.

```
/bin/bash -c "$(curl -fsSL https://static.pantsbuild.org/setup/one_step_setup.sh)" 
```

If the installation process was successful, you will see `Pants was installed successfully!` echoed to your terminal. 

If you had difficulty installing Pants, see our [getting help](doc:getting-help) for community resources to help you resolve your issue.


> 📘 Add `./pants` to version control
> 
> You should check the `./pants` script into your repo so that all users can easily run Pants.

> 👍 Upgrading Pants
> 
> The `./pants` script will automatically install and use the Pants version specified in `pants.toml`, so upgrading Pants is as simple as editing `pants_version` in that file.


Updating the `pants` launch script
----------------------------------

To update to the latest `pants` launch script in an existing repo, run:

```
curl -L -O https://static.pantsbuild.org/setup/pants && chmod +x ./pants
```
