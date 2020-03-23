# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import logging
import os

from pants.ivy.ivy import Ivy
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.util.dirutil import safe_concurrent_creation, safe_delete

logger = logging.getLogger(__name__)


class Bootstrapper:
    """Bootstraps a working ivy resolver.

    By default a working resolver will be bootstrapped from maven central and it will use standard
    public jar repositories and a standard ivy local cache directory to execute resolve operations.

    By default ivy will be bootstrapped from a stable ivy jar version found in maven central, but
    this can be over-ridden with the ``--ivy-bootstrap-jar-urls`` option.

    After bootstrapping, ivy will re-resolve itself.  By default it does this via maven central, but
    a custom ivy tool classpath can be specified by using the ``--ivy-ivy-profile`` option to point to
    a custom ivy profile ivy.xml.  This can be useful to upgrade ivy to a version released after pants
    or else mix in auxiliary jars that provide ivy plugins.

    Finally, by default the ivysettings.xml embedded in the ivy jar will be used in conjunction with
    the default ivy local cache directory of ~/.ivy2/cache.  To specify custom values for these you
    can either provide ``--ivy-ivy-settings`` and ``--ivy-cache-dir`` options.
    """

    class Error(Exception):
        """Indicates an error bootstrapping an ivy classpath."""

    _INSTANCE = None

    @classmethod
    def default_ivy(cls, bootstrap_workunit_factory=None):
        """Returns an Ivy instance using the default global bootstrapper.

        By default runs ivy via a subprocess java executor.  Callers of execute() on the returned
        Ivy instance can provide their own executor.

        :param bootstrap_workunit_factory: the optional workunit to bootstrap under.
        :returns: an Ivy instance.
        :raises: Bootstrapper.Error if the default ivy instance could not be bootstrapped
        """
        return cls.instance().ivy(bootstrap_workunit_factory=bootstrap_workunit_factory)

    def __init__(self, ivy_subsystem=None):
        """Creates an ivy bootstrapper."""
        self._ivy_subsystem = ivy_subsystem or IvySubsystem.global_instance()
        self._version = self._ivy_subsystem.get_options().version
        self._ivyxml = self._ivy_subsystem.get_options().ivy_profile
        self._classpath = None

    @classmethod
    def instance(cls):
        """
        :returns: the default global ivy bootstrapper.
        :rtype: Bootstrapper
        """
        if cls._INSTANCE is None:
            cls._INSTANCE = Bootstrapper()
        return cls._INSTANCE

    @classmethod
    def reset_instance(cls):
        cls._INSTANCE = None

    def ivy(self, bootstrap_workunit_factory=None):
        """Returns an ivy instance bootstrapped by this bootstrapper.

        :param bootstrap_workunit_factory: the optional workunit to bootstrap under.
        :raises: Bootstrapper.Error if ivy could not be bootstrapped
        """
        return Ivy(
            self._get_classpath(bootstrap_workunit_factory),
            ivy_settings=self._ivy_subsystem.get_options().ivy_settings,
            ivy_resolution_cache_dir=self._ivy_subsystem.resolution_cache_dir(),
            extra_jvm_options=self._ivy_subsystem.extra_jvm_options(),
        )

    def _get_classpath(self, workunit_factory):
        """Returns the bootstrapped ivy classpath as a list of jar paths.

        :raises: Bootstrapper.Error if the classpath could not be bootstrapped
        """
        if not self._classpath:
            self._classpath = self._bootstrap_ivy_classpath(workunit_factory)
        return self._classpath

    def _bootstrap_ivy_classpath(self, workunit_factory, retry=True):
        ivy_bootstrap_dir = os.path.join(
            self._ivy_subsystem.get_options().pants_bootstrapdir, "tools", "jvm", "ivy"
        )
        digest = hashlib.sha1()
        if self._ivyxml and os.path.isfile(self._ivyxml):
            with open(self._ivyxml, "rb") as fp:
                digest.update(fp.read())
        digest.update(self._version.encode())
        classpath = os.path.join(ivy_bootstrap_dir, f"{digest.hexdigest()}")

        if not os.path.exists(classpath):
            with safe_concurrent_creation(classpath) as safe_classpath:
                ivy = self._bootstrap_ivy()
                args = ["-confs", "default", "-cachepath", safe_classpath]
                if self._ivyxml and os.path.isfile(self._ivyxml):
                    args.extend(["-ivy", self._ivyxml])
                else:
                    args.extend(["-dependency", "org.apache.ivy", "ivy", self._version])

                try:
                    ivy.execute(
                        args=args, workunit_factory=workunit_factory, workunit_name="ivy-bootstrap"
                    )
                except ivy.Error as e:
                    raise self.Error("Failed to bootstrap an ivy classpath! {}".format(e))

        with open(classpath, "r") as fp:
            cp = fp.read().strip().split(os.pathsep)
            if not all(map(os.path.exists, cp)):
                safe_delete(classpath)
                if retry:
                    return self._bootstrap_ivy_classpath(workunit_factory, retry=False)
                raise self.Error(
                    "Ivy bootstrapping failed - invalid classpath: {}".format(":".join(cp))
                )
            return cp

    def _bootstrap_ivy(self):
        options = self._ivy_subsystem.get_options()
        return Ivy(
            self._ivy_subsystem.select(),
            ivy_settings=options.bootstrap_ivy_settings or options.ivy_settings,
            ivy_resolution_cache_dir=self._ivy_subsystem.resolution_cache_dir(),
            extra_jvm_options=self._ivy_subsystem.extra_jvm_options(),
        )
