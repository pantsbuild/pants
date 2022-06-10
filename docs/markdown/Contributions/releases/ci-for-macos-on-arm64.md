---
title: "GitHub Actions macOS ARM64 runners"
slug: "ci-for-macos-on-arm64"
hidden: false
createdAt: "2022-06-05T15:31:27.665Z"
updatedAt: "2022-06-05T18:34:49.823Z"
---
Apple is phasing out their X86_64 hardware, and all new macOS systems are based on the M1 ARM64 processor. Pants must run on these systems, which means we need an M1 CI machine on which to test and package Pants.

Unfortunately, GitHub Actions does not yet have hosted runners for MacOS ARM64. So we must run our own self-hosted runner. This document describes how to set one up. It is intended primarily for Pants maintainers who have to maintain our CI infrastructure, but since there is not much information online about how to set up self-hosted runners on M1, it may be useful as a reference to other projects as well.

If you find any errors or omissions in this page, please let us know on [Slack](doc:getting-help#slack) or provide corrections via the "Suggest Edits" link above. 

The machine
-----------

As yet there aren't many options for a hosted M1 system:

- AWS has a [preview program](https://aws.amazon.com/about-aws/whats-new/2021/12/amazon-ec2-m1-mac-instances-macos/), which you can sign up for and hope to get into. Once these instances are generally available we can evaluate them as a solution.
- You can buy an M1 machine and stick it in a closet. You take on the risk of compromising your  
  network if the machine is compromised by a rogue CI job. 
- You can rent a cloud-hosted M1 machine by the month from [MacStadium](https://www.macstadium.com/).

We've gone with the MacStadium approach for now.

Setting up the machine
----------------------

### Remote desktop

Since this is machine is [a pet, not cattle](https://iamondemand.com/blog/devops-concepts-pets-vs-cattle/), we allow ourselves a somewhat manual, bespoke setup process (we can script this up if it becomes necessary). One easy way to do this is via VNC remote desktop from another macOS machine (not necessarily an M1). 

To connect to the remote machine, enter `vnc://XXX.XXX.XXX.XXX` on the local machine's Safari address bar, substituting the machine's IP address, as given to you by MacStadium. Safari will prompt you to allow it to open the Screen Sharing app.

Screen Sharing will give you a login prompt. The username is `administrator` and the initial  
password is obtained from MacStadium. 

Once logged in, you can control the remote machine's desktop in the Screen Sharing window, and even share the clipboard across the two machines.

### Change the initial password

Go to  > System Preferences > Users & Groups, select the administrator user,  
click "Change Password..." and select a strong password.

### Ensuring smooth restarts

Go to  > System Preferences > Energy Saver and ensure that Restart After Power Failure is checked.

### Creating a role user

We don't want to run action as the administrator user, so go to  > System Preferences > Users & Groups and create a Standard account with the full name `GitHub Actions Runner`, the account name `gha` and a strong password. 

### Installing software

Most other setup can be done either in a terminal window on the remote desktop, or, more easily,  
by SSH'ing into the remote M1 as `administrator`:

```
$ ssh administrator@XXX.XXX.XXX.XXX
(administrator@XXX.XXX.XXX.XXX) Password:
%
```

Perform the following setup steps as `administrator`:

```
# Install Rosetta2
% softwareupdate --install-rosetta
...
# Install XCode command-line tools
% xcode-select --install
...
# Install Homebrew
% /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
% echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> /Users/administrator/.zprofile   
...
# Install pyenv
% brew install pyenv
...
# Set up pyenv
% echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshenv
% echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshenv    
% echo 'eval "$(pyenv init -)"' >> ~/.zshenv
% source ~/.zshenv
...
# Install Python 3.9
% pyenv install 3.9.13
...
# Install the AWS CLI
% brew install awscli
...


```

### Setting up the role user

First ssh into the remote M1 as `gha`:

```
$ ssh gha@XXX.XXX.XXX.XXX
(gha@XXX.XXX.XXX.XXX) Password:
%
```

Perform the following setup steps as `gha`:

```
# Set up Homebrew
% echo 'export PATH=$PATH:/opt/homebrew/bin/' >> /Users/gha/.zshenv   
...
# Set up pyenv
% echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshenv
% echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshenv    
% echo 'eval "$(pyenv init -)"' >> ~/.zshenv
...
# Install Python 3.9
% pyenv install 3.9.13
...
# Install rustup
% curl https://sh.rustup.rs -sSf | sh
```

Note that we use `.zshenv` because the runner will not execute in an interactive shell. 

Setting up the self-hosted runner
---------------------------------

### Installing the runner

On GitHub's repo page, go to [Settings > Actions > Runners](https://github.com/pantsbuild/pants/settings/actions/runners).

Click "New self-hosted runner", and select macOS and run all the Download and Configure commands it displays, as `gha`, on the remote machine. Set the labels to [self-hosted, macOS, ARM64]. Accept the default values for other settings.

**Note:** The GitHub Actions runner is an X86_64 binary that runs under Rosetta. Therefore its  
  subprocesses will run in X86_64 mode by default as well. So CI processes that care about platform  
  (such as building and packaging native code) must be invoked with the `arch -arm64e` prefix.

### Setting up env vars

The runner requires some env vars to be set up. 

As `gha`, run:

```
% cd actions-runner
% echo 'ImageOS=macos12' >> .env
% echo "XCODE_12_DEVELOPER_DIR=$(xcode-select -p)" >> .env
```

Automating runner invocation
----------------------------

We want the runner to run automatically when the M1 machine restarts. Setting this up requires  
logging in to the remote desktop as `gha`, by entering `vnc://XXX.XXX.XXX.XXX` in Safari as before,  
but using `gha`'s credentials this time.

### Creating an Application

Launch Finder, and go to Applications > Automator. Create a new "Application" file.

Select "Utilities" in the left-hand menu, and then "Run Shell Script" in the submenu.

Leave the shell as `/bin/zsh`, and enter this as the shell command:

```
cd ~/actions-runner && ./run.sh
```

Save the Application file to the `Desktop` under the name "GHA Runner".

### Setting up Login Options

Go to  > System Preferences > Users & Groups, and click the lock to make changes.

Select the GitHub Actions Runner user, then Login Items. Click +, browse to the GHA Runner application on the desktop and select it so that it appears under "These items will open automatically when you log in". 

Click on Login Options and for Automatic login choose Github Actions Runner.

Testing it all out
------------------

Now use the MacStadium web UI to restart the machine. Once it comes back up it  
should be able to pick up any job with this setting:

```
    runs-on:
    - self-hosted
    - macOS
    - ARM64
```

Note that you may need to log in to the remote desktop once before b