# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import io
import os
import shutil
import tarfile
import uuid

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.generator import Generator
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.task.task import Task
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir
from pants.util.process_handler import subprocess
from pkg_resources import resource_string
from six import string_types

from pants.contrib.rpmbuild.targets.remote_rpm_source import RemoteRpmSource
from pants.contrib.rpmbuild.targets.rpm_package import RpmPackageTarget

# Maps platform names to information about the specific platform.
# TODO(tdyas): Put this in pants.ini defaults.
DEFAULT_PLATFORM_METADATA = {
  'centos6': {
    'base': 'centos:6.8',
  },
  'centos7': {
    'base': 'centos:7',
  },
}


class RpmbuildTask(Task):
  """Build a RpmPackageTarget into one or more RPMs using a consistent build environment
  in a Docker container.
  """

  @classmethod
  def register_options(cls, register):
    super(RpmbuildTask, cls).register_options(register)
    register('--platform-metadata', type=dict, default=DEFAULT_PLATFORM_METADATA,
             help='Dictionary mapping platform name to various metadata about the platform')
    register('--platform', default='centos7', help='Sets the platform to build RPMS for.')
    register('--docker', default='docker', help='Path to the docker CLI tool')
    register('--keep-build-products', type=bool, advanced=True,
             help='Do not remove the build directory passed to Docker.')
    register('--docker-build-no-cache', type=bool, advanced=True,
             help='Do not cache the results of `docker build`.')
    register('--docker-build-context-files', type=list, default=[], advanced=True,
             help='Files to copy into the Docker build context.')
    register('--docker-build-setup-commands', type=list, default=[], advanced=True,
             help='Dockerfile commands to inject at top of Dockerfile used for RPM builder image')
    register('--shell-before', type=bool, advanced=True,
             help='Drop to a shell before invoking `rpmbuild`')
    register('--shell-after', type=bool, advanced=True,
             help='Drop to a shell after invoking `rpmbuild`')
    register('--commit-container-image', type=bool, default=False, advanced=True,
             help='After invoking `rpmbuild`, commit the container state to a new image')

  def __init__(self, *args, **kwargs):
    super(RpmbuildTask, self).__init__(*args, **kwargs)

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require('remote_files')
    super(RpmbuildTask, cls).prepare(options, round_manager)

  @classmethod
  def product_types(cls):
    return ['rpms', 'srpms']

  @property
  def create_target_dirs(self):
    return True

  @staticmethod
  def is_rpm_package(target):
    return isinstance(target, RpmPackageTarget)

  @staticmethod
  def write_stream(r, w):
    size = 1024 * 1024  # 1 MB
    buf = r.read(size)
    while buf:
      w.write(buf)
      buf = r.read(size)

  @classmethod
  def _remote_source_targets(cls, rpm_target):
    return [t for t in rpm_target.dependencies if isinstance(t, RemoteRpmSource)]

  def convert_build_req(self, raw_build_reqs):
    pkg_names = []
    for raw_build_req in raw_build_reqs.split(','):
      raw_build_req = raw_build_req.strip()
      pkg_name = raw_build_req.split(' ')[0]
      pkg_names.append(pkg_name)
    return pkg_names

  def extract_build_reqs(self, rpm_spec):
    build_reqs = []

    with io.open(rpm_spec, 'r', encoding='utf8') as f:
      for line in f:
        line = line.strip()
        if line.lower().startswith('buildrequires'):
          raw_build_reqs = line.split(':', 1)[1].strip()
          build_reqs.extend(self.convert_build_req(raw_build_reqs))

    return build_reqs

  def docker_workunit(self, name, cmd):
    return self.context.new_workunit(
      name=name,
      labels=[WorkUnitLabel.TOOL, WorkUnitLabel.RUN],
      log_config=WorkUnit.LogConfig(level=self.get_options().level, colors=self.get_options().colors),
      cmd=' '.join(cmd)
    )

  def build_rpm(self, platform, vt, build_dir):
    # Copy the spec file to the build directory.
    target = vt.target
    rpm_spec_path = os.path.join(get_buildroot(), target.rpm_spec)
    shutil.copy(rpm_spec_path, build_dir)
    spec_basename = os.path.basename(target.rpm_spec)

    # Resolve the build requirements.
    build_reqs = self.extract_build_reqs(rpm_spec_path)
    
    # TODO(mateo): There is a bit of an API conflation now that we have remote_source urls and targets.
    # Especially when you consider that there is also sources/dependencies.
    # The distinction between these things is going to be confusing, they should be unified or at least streamlined.
    local_sources = []
    remote_files = self.context.products.get('remote_files')
    for source in self._remote_source_targets(target):
      mapping = remote_files.get(source)
      # The remote_files product is a mapping of [vt.target] => { vt.results_dir: os.listdir(vt.results_dir)}.
      # The contents could be files or dirs, so both are handled here.
      # TODO(mateo): The files should possibly be set as Source files with defines.
      if mapping:
        for dirname, filenamez in mapping.items():
          for filename in filenamez:
            source_path = os.path.join(dirname, filename)
            # Allow for extracted rmeote sources.
            if os.path.isfile(source_path):
              shutil.copy(source_path, build_dir)
            else:
              shutil.copytree(source_path, build_dir)
            local_sources.append({
              'basename': filename,
            })
    for source_rel_path in target.sources_relative_to_buildroot():
      shutil.copy(os.path.join(get_buildroot(), source_rel_path), build_dir)
      local_sources.append({
        'basename': os.path.basename(source_rel_path),
      })

    # Setup information on remote sources.
    def convert_remote_source(remote_source):
      if isinstance(remote_source, string_types):
        return {'url': remote_source, 'basename': os.path.basename(remote_source)}
      elif isinstance(remote_source, tuple):
        return {'url': remote_source[0], 'basename': remote_source[1]}
      else:
        raise ValueError('invalid remote_sources entry: {}'.format(remote_source))
    remote_sources = [convert_remote_source(rs) for rs in target.remote_sources]

    # Put together rpmbuild options for defines.
    rpmbuild_options = ''
    for key in sorted(target.defines.keys()):
      quoted_value = str(target.defines[key]).replace("\\", "\\\\").replace("\"", "\\\"")
      rpmbuild_options += ' --define="%{} {}"'.format(key, quoted_value)

    # Write the entry point script.
    entrypoint_generator = Generator(
      resource_string(__name__, 'build_rpm.sh.mustache'),
      spec_basename=spec_basename,
      pre_commands=[{'command': '/bin/bash -i'}] if self.get_options().shell_before else [],
      post_commands=[{'command': '/bin/bash -i'}] if self.get_options().shell_after else [],
      rpmbuild_options=rpmbuild_options,
    )
    entrypoint_path = os.path.join(build_dir, 'build_rpm.sh')
    with open(entrypoint_path, 'wb') as f:
      f.write(entrypoint_generator.render())
    os.chmod(entrypoint_path, 0555)

    # Copy globally-configured files into build directory.
    for context_file_path_template in self.get_options().docker_build_context_files:
      context_file_path = context_file_path_template.format(platform_id=platform['id'])
      shutil.copy(context_file_path, build_dir)

    # Determine setup commands.
    setup_commands = [
      {'command': command.format(platform_id=platform['id'])}
      for command in self.get_options().docker_build_setup_commands]

    # Get the RPMs created by the target's RpmPackageTarget dependencies.
    rpm_products = []
    for dep in target.dependencies:
      if isinstance(dep, RpmPackageTarget):
        specs = self.context.products.get('rpms')[dep]
        if specs:
          for dirname, relpath in specs.items():
            for rpmpath in relpath:
              local_rpm = os.path.join(dirname, rpmpath)
              shutil.copy(local_rpm, build_dir)
              rpm_products.append({
                'local_rpm': os.path.basename(rpmpath),
              })

    # Write the Dockerfile for this build.
    dockerfile_generator = Generator(
      resource_string(__name__, 'dockerfile_template.mustache'),
      image=platform['base'],
      setup_commands=setup_commands,
      spec_basename=spec_basename,
      rpm_dependencies=rpm_products,
      build_reqs={'reqs': ' '.join(["'{}'".format(req) for req in build_reqs])} if build_reqs else None,
      local_sources=local_sources,
      remote_sources=remote_sources,
    )
    dockerfile_path = os.path.join(build_dir, 'Dockerfile')
    with open(dockerfile_path, 'wb') as f:
      f.write(dockerfile_generator.render())

    # Generate a UUID to identify the image.
    uuid_identifier = uuid.uuid4()
    image_base_name = 'rpm-image-{}'.format(uuid_identifier)
    image_name = '{}:latest'.format(image_base_name)
    container_name = None

    try:
      # Build the Docker image that will build the RPMS.
      build_image_cmd = [
        self.get_options().docker,
        'build',
      ]
      if self.get_options().docker_build_no_cache:
        build_image_cmd.append('--no-cache')
      build_image_cmd.extend([
        '-t',
        image_name,
        build_dir,
      ])
      with self.docker_workunit(name='build-image', cmd=build_image_cmd) as workunit:
        self.context.log.debug('Executing: {}'.format(' '.join(build_image_cmd)))
        proc = subprocess.Popen(build_image_cmd, stdout=workunit.output('stdout'), stderr=subprocess.STDOUT)
        returncode = proc.wait()
        if returncode != 0:
          raise TaskError('Failed to build image, returncode={0}'.format(returncode))

      # Run the image in a container to actually build the RPMs.
      container_name = 'rpm-container-{}'.format(uuid_identifier)
      run_container_cmd = [
        self.get_options().docker,
        'run',
        '--attach=stderr',
        '--attach=stdout',
        '--name={}'.format(container_name),
      ]
      if self.get_options().shell_before or self.get_options().shell_after:
        run_container_cmd.extend(['-i', '-t'])
      run_container_cmd.extend([
        image_name,
      ])
      with self.docker_workunit(name='run-container', cmd=run_container_cmd) as workunit:
        proc = subprocess.Popen(run_container_cmd, stdout=workunit.output('stdout'), stderr=subprocess.STDOUT)
        returncode = proc.wait()
        if returncode != 0:
          raise TaskError('Failed to build RPM, returncode={0}'.format(returncode))

      # TODO(mateo): Convert this to output to a per-platform namespace to make it easy to upload all RPMs to the
      # correct platform (something like: `dist/rpmbuilder/centos7/x86_64/foo.rpm`).
      #
      # Extract the built RPMs from the container.
      extract_rpms_cmd = [
        self.get_options().docker,
        'export',
        container_name,
      ]
      with self.docker_workunit(name='extract-rpms', cmd=extract_rpms_cmd) as workunit:
        proc = subprocess.Popen(extract_rpms_cmd, stdout=subprocess.PIPE, stderr=None)
        with tarfile.open(fileobj=proc.stdout, mode='r|*') as tar:
          for entry in tar:
            name = entry.name
            if (name.startswith('home/rpmuser/rpmbuild/RPMS/') or name.startswith('home/rpmuser/rpmbuild/SRPMS/')) and name.endswith('.rpm'):
              rel_rpm_path = name.lstrip('home/rpmuser/rpmbuild/')
              if rel_rpm_path:
                rpmdir = os.path.dirname(rel_rpm_path)
                safe_mkdir(os.path.join(vt.results_dir, rpmdir))
                rpmfile = os.path.join(vt.results_dir, rel_rpm_path)

                self.context.log.info('Extracting {}'.format(rel_rpm_path))
                fileobj = tar.extractfile(entry)
                # NOTE(mateo): I believe it has free streaming w/ context manager/stream mode. But this doesn't hurt!
                with open(rpmfile, 'wb') as f:
                  self.write_stream(fileobj, f)
                output_dir = os.path.join(self.get_options().pants_distdir, 'rpmbuild', rpmdir)
                safe_mkdir(output_dir)
                shutil.copy(rpmfile, output_dir)
                if name.startswith('home/rpmuser/rpmbuild/RPMS/'):
                  self.context.products.get('rpms').add(vt.target, vt.results_dir).append(rel_rpm_path)
                else:
                  self.context.products.get('srpms').add(vt.target, vt.results_dir).append(rel_rpm_path)

        retcode = proc.wait()
        if retcode != 0:
          raise TaskError('Failed to extract RPMS')
        else:
          # Save the resulting image if asked. Eventually this image should be pushed to the registry every build,
          # and subsequent invocations on the published RPM should simply pull and extract.
          if self.get_options().commit_container_image:
            commited_name = 'rpm-commited-image-{}'.format(uuid_identifier)
            self.context.log.info('Saving container state as image...')
            docker_commit_cmd = [self.get_options().docker, 'commit', container_name]
            with self.docker_workunit(name='commit-to-image', cmd=docker_commit_cmd) as workunit:
              subprocess.call(docker_commit_cmd, stdout=workunit.output('stdout'), stderr=subprocess.STDOUT)
              self.context.log.info('Saved container as image: {}\n'.format(commited_name))

    finally:
      # Remove the build container.
      if container_name and not self.get_options().keep_build_products:
        remove_container_cmd = [self.get_options().docker, 'rm', container_name]
        with self.docker_workunit(name='remove-build-container', cmd=remove_container_cmd) as workunit:
          subprocess.call(remove_container_cmd, stdout=workunit.output('stdout'), stderr=subprocess.STDOUT)

      # Remove the build image.
      if not self.get_options().keep_build_products:
        remove_image_cmd = [self.get_options().docker, 'rmi', image_name]
        with self.docker_workunit(name='remove-build-image', cmd=remove_image_cmd) as workunit:
          subprocess.call(remove_image_cmd, stdout=workunit.output('stdout'), stderr=subprocess.STDOUT)

  def execute(self):
    platform_key = self.get_options().platform
    try:
      platform = self.get_options().platform_metadata[platform_key]
      platform['id'] = platform_key
    except KeyError:
      raise TaskError('Unknown platform {}'.format(platform_key))

    targets = self.context.targets(self.is_rpm_package)
    with self.invalidated(targets, invalidate_dependents=True, topological_order=True) as invalidation_check:
      # Use of invalidation to establish workdir and to get dependency management - all targets in context are built.
      for vt in invalidation_check.all_vts:
        with temporary_dir(cleanup=not self.get_options().keep_build_products) as build_dir:
          self.context.log.debug('Build directory: {}'.format(build_dir))
          self.context.log.info('Building RPM: {} ...'.format(vt.target.name))
          self.build_rpm(platform, vt, build_dir)
