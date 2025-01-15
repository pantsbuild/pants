# Packer config to create the AMI we use with https://runs-on.com/
# for custom Linux-ARM64 CI runners.

# RunsOn deprecate features periodically, and eventually refuse to work with old AMIs.
# So we need to recreate the AMI every few weeks. Currently we do this manually,
# but should consider automating it.

# To create the AMI using this config:
#
# Preliminaries:
#
# 1. Install Packer: https://developer.hashicorp.com/packer/tutorials/docker-get-started/get-started-install-cli
#
# 2. Ensure that you have CLI credentials for an IAM user in the pantsbuild AWS account,
#    and that this user has the relevant permissions (e.g., by attaching
#    the PackerAmazonPlugin policy). We'll assume that this user's creds are in
#    a profile called `pants` in ~/.aws/credentials.
#
# Running Packer:
#
# 1. Run `packer init build-support/packer/runson/runson.pkr.hcl` to initialize state.
#
# 2. Per our policy, your user must use MFA. So you must acquire temporary credentials to pass to Packer:
#
#    `aws --profile=pants sts get-session-token --serial-number arn:aws:iam::AWSACCOUNTID:mfa/USERNAME --token-code XXXXXX`
#    Where AWSACCOUNTID is pantsbuild's AWS account ID, USERNAME is your username, and XXXXXX is the code
#    generated by your MFA token.
#
#    This will emit temporary credentials as follows:
#
#    {
#        "Credentials": {
#            "AccessKeyId": "ACCESSKEYID",
#            "SecretAccessKey": "SECRETACCESSKEY",
#            "SessionToken": "SESSIONTOKEN",
#        }
#    }
#
# 3. Run Packer build with the temporary creds:
#    ```
#    AWS_ACCESS_KEY_ID=ACCESSKEYID AWS_SECRET_ACCESS_KEY=SECRETACCESSKEY AWS_SESSION_TOKEN=SESSIONTOKEN \
#      packer build build-support/packer/runson/runson.pkr.hcl
#    ```
#
#    This will take ~7 minutes but will eventually give you the ID of the AMI:
#
#    ```
#    ==> Builds finished. The artifacts of successful builds are:
#    --> build-custom-runson-ami.amazon-ebs.runson: AMIs were created:
#    us-east-1: AMI-ID
#    ```
#
# Updating RunsOn Config:
#
#  1. Create a PR that sets the `ami` field in .github/runs-on.yml to this new AMI-ID.
#     Once this PR is merged into the main branch, RunsOn will start using the new AMI
#     when it creates on-the-fly CI runners.
#
#     Note that since the Pants repo is public, RunsOn will only use config in the default
#     branch of the repo, in our case `main`. If the reason you're updating the AMI is that
#     CI is failing on an expired previous AMI, you will need to merge into main without green CI.
#     This will require you to temporarily disable the branch protection rule on main.
#
#  2. Once the new config is in main, and any in-flight CI runs have finished, we can deregister
#     the old AMI via the AWS web console, to avoid confusion.
#
# NOTE: If you edit this file, run `packer fmt build-support/packer/runson/runson.pkr.hcl` to format it
#       and `packer validate build-support/packer/runson/runson.pkr.hcl` to validate it.
#
# See https://runs-on.com/guides/building-custom-ami-with-packer/ for RunsOn's documentation relating
# to generating compatible AMIs with Packer.

packer {
  required_plugins {
    amazon = {
      version = ">= 1.2.8"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

source "amazon-ebs" "runson" {
  ami_name      = "ubuntu22-full-arm64-python3.7-3.13-{{timestamp}}"
  instance_type = "t4g.nano"
  region        = "us-east-1"
  source_ami_filter {
    filters = {
      name                = "runs-on-v2.2-ubuntu22-full-arm64-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["135269210855"] # RunsOn's AWS account ID
  }
  # Packer creates a temporary keypair on the temporary instance it uses
  # to create the AMI, so we don't need to configure that.
  ssh_username = "ubuntu"
  user_data    = "#!/bin/bash\nsystemctl start ssh"
}

build {
  name = "build-custom-runson-ami"
  sources = [
    "source.amazon-ebs.runson"
  ]
  provisioner "shell" {
    inline = [
      "sudo apt-get install -y software-properties-common",
      "sudo add-apt-repository -y ppa:deadsnakes/ppa",
      "sudo apt-get update",
      "sudo apt-get install -y \\",
      "python3.7 python3.7-dev python3.7-venv \\",
      "python3.8 python3.8-dev python3.8-venv \\",
      "python3.9 python3.9-dev python3.9-venv \\",
      "python3.10 python3.10-dev python3.10-venv \\",
      "python3.11 python3.11-dev python3.11-venv \\",
      "python3.12 python3.12-dev python3.12-venv \\",
      "python3.13 python3.13-dev python3.13-venv",
    ]
  }
}
