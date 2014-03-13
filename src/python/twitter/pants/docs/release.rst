###############
Release Process
###############

This page describes how to make a versioned release of Pants.

.. note:: As of March 2014 this process is being formalized. If doing releases,
          please check back often as the process is evolving.

At a high level, releasing pants involves:

* Deciding what/when to release. At present this is ad-hoc, typically when
  a change has been made and the author wants to use a version incorporating
  that change.
* Publish to PyPi.
* Announce the release on `pants-users`.


***************
Publish to PyPi
***************

Pants and the common libraries are published to the
`Python Package Index <https://pypi.python.org/pypi>`_ per the Python
community convention.

At this time version numbers are checked-into BUILD files. Send a review
updating version numbers for the libraries you will be publishing. You can
generate a list of libraries requiring publishing with: ::

   $ ./pants.bootstrap goal dependencies \
       src/python/twitter/pants:_pants_transitional_publishable_library_ | sort -u | grep -v =
   src/python/twitter/common/collections/BUILD:collections
   src/python/twitter/common/config/BUILD:config
   src/python/twitter/common/confluence/BUILD:confluence
   <SNIP>

After updating the checked-in version numbers, publish locally and verify the release. ::

   PANTS_DEV=1 ./pants.bootstrap setup_py --recursive src/python/twitter/pants:pants-packaged
   VENV_DIR=$(mktemp -d -t pants.XXXXX)
   virtualenv $VENV_DIR
   source $VENV_DIR/bin/activate
   pip install --allow-external elementtree --allow-unverified elementtree \
     --find-links=file://$(pwd)/dist twitter.pants==0.0.17
   pants goal list ::
   deactivate

Now that we've smoke-tested this release, publish to PyPi. ::

   PANTS_DEV=1 ./pants.bootstrap setup_py --recursive --run='sdist upload' \
     src/python/twitter/pants:pants-packaged

Check PyPi to ensure everything looks good. Finally, announce the release to
`pants-users` and `pants-devel`.
