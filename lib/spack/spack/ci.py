# Copyright 2013-2020 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import base64
import datetime
import json
import os
import shutil
import tempfile
import zlib

from six import iteritems
from six.moves.urllib.error import HTTPError, URLError
from six.moves.urllib.parse import urlencode
from six.moves.urllib.request import build_opener, HTTPHandler, Request

import llnl.util.tty as tty

import spack
import spack.binary_distribution as bindist
import spack.cmd.buildcache as buildcache
import spack.compilers as compilers
import spack.config as cfg
import spack.environment as ev
from spack.error import SpackError
import spack.hash_types as ht
from spack.main import SpackCommand
import spack.repo
from spack.spec import Spec
import spack.util.spack_yaml as syaml
import spack.util.web as web_util


JOB_RETRY_CONDITIONS = [
    'always',
]

spack_gpg = SpackCommand('gpg')
spack_compiler = SpackCommand('compiler')


class TemporaryDirectory(object):
    def __init__(self):
        self.temporary_directory = tempfile.mkdtemp()

    def __enter__(self):
        return self.temporary_directory

    def __exit__(self, exc_type, exc_value, exc_traceback):
        shutil.rmtree(self.temporary_directory)
        return False


def _create_buildgroup(opener, headers, url, project, group_name, group_type):
    data = {
        "newbuildgroup": group_name,
        "project": project,
        "type": group_type
    }

    enc_data = json.dumps(data).encode('utf-8')

    request = Request(url, data=enc_data, headers=headers)

    response = opener.open(request)
    response_code = response.getcode()

    if response_code != 200 and response_code != 201:
        msg = 'Creating buildgroup failed (response code = {0}'.format(
            response_code)
        raise SpackError(msg)

    response_text = response.read()
    response_json = json.loads(response_text)
    build_group_id = response_json['id']

    return build_group_id


def populate_buildgroup(job_names, group_name, project, site,
                        credentials, cdash_url):
    url = "{0}/api/v1/buildgroup.php".format(cdash_url)

    headers = {
        'Authorization': 'Bearer {0}'.format(credentials),
        'Content-Type': 'application/json',
    }

    opener = build_opener(HTTPHandler)

    parent_group_id = _create_buildgroup(
        opener, headers, url, project, group_name, 'Daily')
    group_id = _create_buildgroup(
        opener, headers, url, project, 'Latest {0}'.format(group_name),
        'Latest')

    if not parent_group_id or not group_id:
        msg = 'Failed to create or retrieve buildgroups for {0}'.format(
            group_name)
        raise SpackError(msg)

    data = {
        'project': project,
        'buildgroupid': group_id,
        'dynamiclist': [{
            'match': name,
            'parentgroupid': parent_group_id,
            'site': site
        } for name in job_names]
    }

    enc_data = json.dumps(data).encode('utf-8')

    request = Request(url, data=enc_data, headers=headers)
    request.get_method = lambda: 'PUT'

    response = opener.open(request)
    response_code = response.getcode()

    if response_code != 200:
        msg = 'Error response code ({0}) in populate_buildgroup'.format(
            response_code)
        raise SpackError(msg)


def is_main_phase(phase_name):
    return True if phase_name == 'specs' else False


def get_job_name(phase, strip_compiler, spec, osarch, build_group):
    item_idx = 0
    format_str = ''
    format_args = []

    if phase:
        format_str += '({{{0}}})'.format(item_idx)
        format_args.append(phase)
        item_idx += 1

    format_str += ' {{{0}}}'.format(item_idx)
    format_args.append(spec.name)
    item_idx += 1

    format_str += '/{{{0}}}'.format(item_idx)
    format_args.append(spec.dag_hash(7))
    item_idx += 1

    format_str += ' {{{0}}}'.format(item_idx)
    format_args.append(spec.version)
    item_idx += 1

    if is_main_phase(phase) is True or strip_compiler is False:
        format_str += ' {{{0}}}'.format(item_idx)
        format_args.append(spec.compiler)
        item_idx += 1

    format_str += ' {{{0}}}'.format(item_idx)
    format_args.append(osarch)
    item_idx += 1

    if build_group:
        format_str += ' {{{0}}}'.format(item_idx)
        format_args.append(build_group)
        item_idx += 1

    return format_str.format(*format_args)


def get_cdash_build_name(spec, build_group):
    return '{0}@{1}%{2} arch={3} ({4})'.format(
        spec.name, spec.version, spec.compiler, spec.architecture, build_group)


def get_spec_string(spec):
    format_elements = [
        '{name}{@version}',
        '{%compiler}',
    ]

    if spec.architecture:
        format_elements.append(' {arch=architecture}')

    return spec.format(''.join(format_elements))


def format_root_spec(spec, main_phase, strip_compiler):
    if main_phase is False and strip_compiler is True:
        return '{0}@{1} arch={2}'.format(
            spec.name, spec.version, spec.architecture)
    else:
        spec_yaml = spec.to_yaml(hash=ht.build_hash).encode('utf-8')
        return str(base64.b64encode(zlib.compress(spec_yaml)).decode('utf-8'))
        # return '{0}@{1}%{2} arch={3}'.format(
        #     spec.name, spec.version, spec.compiler, spec.architecture)


def spec_deps_key_label(s):
    return s.dag_hash(), "%s/%s" % (s.name, s.dag_hash(7))


def _add_dependency(spec_label, dep_label, deps):
    if spec_label == dep_label:
        return
    if spec_label not in deps:
        deps[spec_label] = set()
    deps[spec_label].add(dep_label)


def get_spec_dependencies(specs, deps, spec_labels):
    spec_deps_obj = compute_spec_deps(specs)

    if spec_deps_obj:
        dependencies = spec_deps_obj['dependencies']
        specs = spec_deps_obj['specs']

        for entry in specs:
            spec_labels[entry['label']] = {
                'spec': Spec(entry['spec']),
                'rootSpec': entry['root_spec'],
            }

        for entry in dependencies:
            _add_dependency(entry['spec'], entry['depends'], deps)


def stage_spec_jobs(specs):
    """Take a set of release specs and generate a list of "stages", where the
        jobs in any stage are dependent only on jobs in previous stages.  This
        allows us to maximize build parallelism within the gitlab-ci framework.

    Arguments:
        specs (Iterable): Specs to build

    Returns: A tuple of information objects describing the specs, dependencies
        and stages:

        spec_labels: A dictionary mapping the spec labels which are made of
            (pkg-name/hash-prefix), to objects containing "rootSpec" and "spec"
            keys.  The root spec is the spec of which this spec is a dependency
            and the spec is the formatted spec string for this spec.

        deps: A dictionary where the keys should also have appeared as keys in
            the spec_labels dictionary, and the values are the set of
            dependencies for that spec.

        stages: An ordered list of sets, each of which contains all the jobs to
            built in that stage.  The jobs are expressed in the same format as
            the keys in the spec_labels and deps objects.

    """

    # The convenience method below, "remove_satisfied_deps()", does not modify
    # the "deps" parameter.  Instead, it returns a new dictionary where only
    # dependencies which have not yet been satisfied are included in the
    # return value.
    def remove_satisfied_deps(deps, satisfied_list):
        new_deps = {}

        for key, value in iteritems(deps):
            new_value = set([v for v in value if v not in satisfied_list])
            if new_value:
                new_deps[key] = new_value

        return new_deps

    deps = {}
    spec_labels = {}

    get_spec_dependencies(specs, deps, spec_labels)

    # Save the original deps, as we need to return them at the end of the
    # function.  In the while loop below, the "dependencies" variable is
    # overwritten rather than being modified each time through the loop,
    # thus preserving the original value of "deps" saved here.
    dependencies = deps
    unstaged = set(spec_labels.keys())
    stages = []

    while dependencies:
        dependents = set(dependencies.keys())
        next_stage = unstaged.difference(dependents)
        stages.append(next_stage)
        unstaged.difference_update(next_stage)
        # Note that "dependencies" is a dictionary mapping each dependent
        # package to the set of not-yet-handled dependencies.  The final step
        # below removes all the dependencies that are handled by this stage.
        dependencies = remove_satisfied_deps(dependencies, next_stage)

    if unstaged:
        stages.append(unstaged.copy())

    return spec_labels, deps, stages


def print_staging_summary(spec_labels, dependencies, stages):
    if not stages:
        return

    tty.msg('  Staging summary:')
    stage_index = 0
    for stage in stages:
        tty.msg('    stage {0} ({1} jobs):'.format(stage_index, len(stage)))

        for job in sorted(stage):
            s = spec_labels[job]['spec']
            tty.msg('      {0} -> {1}'.format(job, get_spec_string(s)))

        stage_index += 1


def compute_spec_deps(spec_list):
    """
    Computes all the dependencies for the spec(s) and generates a JSON
    object which provides both a list of unique spec names as well as a
    comprehensive list of all the edges in the dependency graph.  For
    example, given a single spec like 'readline@7.0', this function
    generates the following JSON object:

    .. code-block:: JSON

       {
           "dependencies": [
               {
                   "depends": "readline/ip6aiun",
                   "spec": "readline/ip6aiun"
               },
               {
                   "depends": "ncurses/y43rifz",
                   "spec": "readline/ip6aiun"
               },
               {
                   "depends": "ncurses/y43rifz",
                   "spec": "readline/ip6aiun"
               },
               {
                   "depends": "pkgconf/eg355zb",
                   "spec": "ncurses/y43rifz"
               },
               {
                   "depends": "pkgconf/eg355zb",
                   "spec": "readline/ip6aiun"
               }
           ],
           "specs": [
               {
                 "root_spec": "readline@7.0%clang@9.1.0-apple arch=darwin-...",
                 "spec": "readline@7.0%clang@9.1.0-apple arch=darwin-highs...",
                 "label": "readline/ip6aiun"
               },
               {
                 "root_spec": "readline@7.0%clang@9.1.0-apple arch=darwin-...",
                 "spec": "ncurses@6.1%clang@9.1.0-apple arch=darwin-highsi...",
                 "label": "ncurses/y43rifz"
               },
               {
                 "root_spec": "readline@7.0%clang@9.1.0-apple arch=darwin-...",
                 "spec": "pkgconf@1.5.4%clang@9.1.0-apple arch=darwin-high...",
                 "label": "pkgconf/eg355zb"
               }
           ]
       }

    """
    spec_labels = {}

    specs = []
    dependencies = []

    def append_dep(s, d):
        dependencies.append({
            'spec': s,
            'depends': d,
        })

    for spec in spec_list:
        spec.concretize()

        # root_spec = get_spec_string(spec)
        root_spec = spec

        rkey, rlabel = spec_deps_key_label(spec)

        for s in spec.traverse(deptype=all):
            if s.external:
                tty.msg('Will not stage external pkg: {0}'.format(s))
                continue

            skey, slabel = spec_deps_key_label(s)
            spec_labels[slabel] = {
                'spec': get_spec_string(s),
                'root': root_spec,
            }
            append_dep(rlabel, slabel)

            for d in s.dependencies(deptype=all):
                dkey, dlabel = spec_deps_key_label(d)
                if d.external:
                    tty.msg('Will not stage external dep: {0}'.format(d))
                    continue

                append_dep(slabel, dlabel)

    for spec_label, spec_holder in spec_labels.items():
        specs.append({
            'label': spec_label,
            'spec': spec_holder['spec'],
            'root_spec': spec_holder['root'],
        })

    deps_json_obj = {
        'specs': specs,
        'dependencies': dependencies,
    }

    return deps_json_obj


def spec_matches(spec, match_string):
    return spec.satisfies(match_string)


def find_matching_config(spec, ci_mappings):
    for ci_mapping in ci_mappings:
        for match_string in ci_mapping['match']:
            if spec_matches(spec, match_string):
                return ci_mapping['runner-attributes']
    return None


def pkg_name_from_spec_label(spec_label):
    return spec_label[:spec_label.index('/')]


def format_job_needs(phase_name, strip_compilers, dep_jobs,
                     osname, build_group, enable_artifacts_buildcache):
    needs_list = []
    for dep_job in dep_jobs:
        needs_list.append({
            'job': get_job_name(phase_name,
                                strip_compilers,
                                dep_job,
                                osname,
                                build_group),
            'artifacts': enable_artifacts_buildcache,
        })
    return needs_list


def generate_gitlab_ci_yaml(env, print_summary, output_file,
                            custom_spack_repo=None, custom_spack_ref=None):
    # FIXME: What's the difference between one that opens with 'spack'
    # and one that opens with 'env'?  This will only handle the former.
    with spack.concretize.disable_compiler_existence_check():
        env.concretize()

    yaml_root = ev.config_dict(env.yaml)

    if 'gitlab-ci' not in yaml_root:
        tty.die('Environment yaml does not have "gitlab-ci" section')

    gitlab_ci = yaml_root['gitlab-ci']
    ci_mappings = gitlab_ci['mappings']

    final_job_config = None
    if 'final-stage-rebuild-index' in gitlab_ci:
        final_job_config = gitlab_ci['final-stage-rebuild-index']

    build_group = None
    enable_cdash_reporting = False
    cdash_auth_token = None

    if 'cdash' in yaml_root:
        enable_cdash_reporting = True
        ci_cdash = yaml_root['cdash']
        build_group = ci_cdash['build-group']
        cdash_url = ci_cdash['url']
        cdash_project = ci_cdash['project']
        cdash_site = ci_cdash['site']

        if 'SPACK_CDASH_AUTH_TOKEN' in os.environ:
            tty.verbose("Using CDash auth token from environment")
            cdash_auth_token = os.environ.get('SPACK_CDASH_AUTH_TOKEN')

    is_pr_pipeline = (
        os.environ.get('SPACK_IS_PR_PIPELINE', '').lower() == 'true'
    )

    # Make sure we use a custom spack if necessary
    before_script = None
    after_script = None
    if custom_spack_repo:
        if not custom_spack_ref:
            custom_spack_ref = 'master'
        before_script = [
            ('git clone "{0}"'.format(custom_spack_repo)),
            'pushd ./spack && git checkout "{0}" && popd'.format(
                custom_spack_ref),
            '. "./spack/share/spack/setup-env.sh"',
        ]
        after_script = [
            'rm -rf "./spack"'
        ]

    ci_mirrors = yaml_root['mirrors']
    mirror_urls = [url for url in ci_mirrors.values()]

    enable_artifacts_buildcache = False
    if 'enable-artifacts-buildcache' in gitlab_ci:
        enable_artifacts_buildcache = gitlab_ci['enable-artifacts-buildcache']

    bootstrap_specs = []
    phases = []
    if 'bootstrap' in gitlab_ci:
        for phase in gitlab_ci['bootstrap']:
            try:
                phase_name = phase.get('name')
                strip_compilers = phase.get('compiler-agnostic')
            except AttributeError:
                phase_name = phase
                strip_compilers = False
            phases.append({
                'name': phase_name,
                'strip-compilers': strip_compilers,
            })

            for bs in env.spec_lists[phase_name]:
                bootstrap_specs.append({
                    'spec': bs,
                    'phase-name': phase_name,
                    'strip-compilers': strip_compilers,
                })

    phases.append({
        'name': 'specs',
        'strip-compilers': False,
    })

    staged_phases = {}
    for phase in phases:
        phase_name = phase['name']
        with spack.concretize.disable_compiler_existence_check():
            staged_phases[phase_name] = stage_spec_jobs(
                env.spec_lists[phase_name])

    if print_summary:
        for phase in phases:
            phase_name = phase['name']
            tty.msg('Stages for phase "{0}"'.format(phase_name))
            phase_stages = staged_phases[phase_name]
            print_staging_summary(*phase_stages)

    all_job_names = []
    output_object = {}
    job_id = 0
    stage_id = 0

    stage_names = []

    max_length_needs = 0
    max_needs_job = ''

    for phase in phases:
        phase_name = phase['name']
        strip_compilers = phase['strip-compilers']

        main_phase = is_main_phase(phase_name)
        spec_labels, dependencies, stages = staged_phases[phase_name]

        for stage_jobs in stages:
            stage_name = 'stage-{0}'.format(stage_id)
            stage_names.append(stage_name)
            stage_id += 1

            for spec_label in stage_jobs:
                root_spec = spec_labels[spec_label]['rootSpec']
                pkg_name = pkg_name_from_spec_label(spec_label)
                release_spec = root_spec[pkg_name]

                runner_attribs = find_matching_config(
                    release_spec, ci_mappings)

                if not runner_attribs:
                    tty.warn('No match found for {0}, skipping it'.format(
                        release_spec))
                    continue

                tags = [tag for tag in runner_attribs['tags']]

                variables = {}
                if 'variables' in runner_attribs:
                    variables.update(runner_attribs['variables'])

                image_name = None
                image_entry = None
                if 'image' in runner_attribs:
                    build_image = runner_attribs['image']
                    try:
                        image_name = build_image.get('name')
                        entrypoint = build_image.get('entrypoint')
                        image_entry = [p for p in entrypoint]
                    except AttributeError:
                        image_name = build_image

                osname = str(release_spec.architecture)
                job_name = get_job_name(phase_name, strip_compilers,
                                        release_spec, osname, build_group)

                debug_flag = ''
                if 'enable-debug-messages' in gitlab_ci:
                    debug_flag = '-d '

                job_scripts = ['spack {0}ci rebuild'.format(debug_flag)]

                compiler_action = 'NONE'
                if len(phases) > 1:
                    compiler_action = 'FIND_ANY'
                    if is_main_phase(phase_name):
                        compiler_action = 'INSTALL_MISSING'

                job_vars = {
                    'SPACK_ROOT_SPEC': format_root_spec(
                        root_spec, main_phase, strip_compilers),
                    'SPACK_JOB_SPEC_PKG_NAME': release_spec.name,
                    'SPACK_COMPILER_ACTION': compiler_action,
                    'SPACK_IS_PR_PIPELINE': str(is_pr_pipeline),
                }

                job_dependencies = []
                if spec_label in dependencies:
                    if enable_artifacts_buildcache:
                        dep_jobs = [
                            d for d in release_spec.traverse(deptype=all,
                                                             root=False)
                        ]
                    else:
                        dep_jobs = []
                        for dep_label in dependencies[spec_label]:
                            dep_pkg = pkg_name_from_spec_label(dep_label)
                            dep_root = spec_labels[dep_label]['rootSpec']
                            dep_jobs.append(dep_root[dep_pkg])

                    job_dependencies.extend(
                        format_job_needs(phase_name, strip_compilers, dep_jobs,
                                         osname, build_group,
                                         enable_artifacts_buildcache))

                # This next section helps gitlab make sure the right
                # bootstrapped compiler exists in the artifacts buildcache by
                # creating an artificial dependency between this spec and its
                # compiler.  So, if we are in the main phase, and if the
                # compiler we are supposed to use is listed in any of the
                # bootstrap spec lists, then we will add more dependencies to
                # the job (that compiler and maybe it's dependencies as well).
                if is_main_phase(phase_name):
                    compiler_pkg_spec = compilers.pkg_spec_for_compiler(
                        release_spec.compiler)
                    for bs in bootstrap_specs:
                        bs_arch = bs['spec'].architecture
                        if (bs['spec'].satisfies(compiler_pkg_spec) and
                            bs_arch == release_spec.architecture):
                            # We found the bootstrap compiler this release spec
                            # should be built with, so for DAG scheduling
                            # purposes, we will at least add the compiler spec
                            # to the jobs "needs".  But if artifact buildcache
                            # is enabled, we'll have to add all transtive deps
                            # of the compiler as well.
                            dep_jobs = [bs['spec']]
                            if enable_artifacts_buildcache:
                                dep_jobs = [
                                    d for d in bs['spec'].traverse(deptype=all)
                                ]

                            job_dependencies.extend(
                                format_job_needs(bs['phase-name'],
                                                 bs['strip-compilers'],
                                                 dep_jobs,
                                                 str(bs_arch),
                                                 build_group,
                                                 enable_artifacts_buildcache))

                if enable_cdash_reporting:
                    cdash_build_name = get_cdash_build_name(
                        release_spec, build_group)
                    all_job_names.append(cdash_build_name)

                    related_builds = []      # Used for relating CDash builds
                    if spec_label in dependencies:
                        related_builds = (
                            [spec_labels[d]['spec'].name
                                for d in dependencies[spec_label]])

                    job_vars['SPACK_CDASH_BUILD_NAME'] = cdash_build_name
                    job_vars['SPACK_RELATED_BUILDS_CDASH'] = ';'.join(
                        sorted(related_builds))

                variables.update(job_vars)

                artifact_paths = [
                    'jobs_scratch_dir',
                    'cdash_report',
                ]

                if enable_artifacts_buildcache:
                    bc_root = 'local_mirror/build_cache'
                    artifact_paths.extend([os.path.join(bc_root, p) for p in [
                        bindist.tarball_name(release_spec, '.spec.yaml'),
                        bindist.tarball_name(release_spec, '.cdashid'),
                        bindist.tarball_directory_name(release_spec),
                    ]])

                job_object = {
                    'stage': stage_name,
                    'variables': variables,
                    'script': job_scripts,
                    'tags': tags,
                    'artifacts': {
                        'paths': artifact_paths,
                        'when': 'always',
                    },
                    'needs': sorted(job_dependencies, key=lambda d: d['job']),
                    'retry': {
                        'max': 2,
                        'when': JOB_RETRY_CONDITIONS,
                    }
                }

                length_needs = len(job_dependencies)
                if length_needs > max_length_needs:
                    max_length_needs = length_needs
                    max_needs_job = job_name

                if before_script:
                    job_object['before_script'] = before_script

                if after_script:
                    job_object['after_script'] = after_script

                if image_name:
                    job_object['image'] = image_name
                    if image_entry is not None:
                        job_object['image'] = {
                            'name': image_name,
                            'entrypoint': image_entry,
                        }

                output_object[job_name] = job_object
                job_id += 1

    tty.debug('{0} build jobs generated in {1} stages'.format(
        job_id, stage_id))

    tty.debug('The max_needs_job is {0}, with {1} needs'.format(
        max_needs_job, max_length_needs))

    # Use "all_job_names" to populate the build group for this set
    if enable_cdash_reporting and cdash_auth_token:
        try:
            populate_buildgroup(all_job_names, build_group, cdash_project,
                                cdash_site, cdash_auth_token, cdash_url)
        except (SpackError, HTTPError, URLError) as err:
            tty.warn('Problem populating buildgroup: {0}'.format(err))
    else:
        tty.warn('Unable to populate buildgroup without CDash credentials')

    if final_job_config and not is_pr_pipeline:
        # Add an extra, final job to regenerate the index
        final_stage = 'stage-rebuild-index'
        final_job = {
            'stage': final_stage,
            'script': 'spack buildcache update-index -d {0}'.format(
                mirror_urls[0]),
            'tags': final_job_config['tags']
        }
        if 'image' in final_job_config:
            final_job['image'] = final_job_config['image']
        if before_script:
            final_job['before_script'] = before_script
        if after_script:
            final_job['after_script'] = after_script
        output_object['rebuild-index'] = final_job
        stage_names.append(final_stage)

    output_object['stages'] = stage_names

    sorted_output = {}
    for output_key, output_value in sorted(output_object.items()):
        sorted_output[output_key] = output_value

    with open(output_file, 'w') as outf:
        outf.write(syaml.dump_config(sorted_output, default_flow_style=True))


def url_encode_string(input_string):
    encoded_keyval = urlencode({'donotcare': input_string})
    eq_idx = encoded_keyval.find('=') + 1
    encoded_value = encoded_keyval[eq_idx:]
    return encoded_value


def import_signing_key(base64_signing_key):
    if not base64_signing_key:
        tty.warn('No key found for signing/verifying packages')
        return

    tty.debug('ci.import_signing_key() will attempt to import a key')

    # This command has the side-effect of creating the directory referred
    # to as GNUPGHOME in setup_environment()
    list_output = spack_gpg('list', output=str)

    tty.debug('spack gpg list:')
    tty.debug(list_output)

    decoded_key = base64.b64decode(base64_signing_key)
    if isinstance(decoded_key, bytes):
        decoded_key = decoded_key.decode('utf8')

    with TemporaryDirectory() as tmpdir:
        sign_key_path = os.path.join(tmpdir, 'signing_key')
        with open(sign_key_path, 'w') as fd:
            fd.write(decoded_key)

        key_import_output = spack_gpg('trust', sign_key_path, output=str)
        tty.debug('spack gpg trust {0}'.format(sign_key_path))
        tty.debug(key_import_output)

    # Now print the keys we have for verifying and signing
    trusted_keys_output = spack_gpg('list', '--trusted', output=str)
    signing_keys_output = spack_gpg('list', '--signing', output=str)

    tty.debug('spack gpg list --trusted')
    tty.debug(trusted_keys_output)
    tty.debug('spack gpg list --signing')
    tty.debug(signing_keys_output)


def configure_compilers(compiler_action, scope=None):
    if compiler_action == 'INSTALL_MISSING':
        tty.debug('Make sure bootstrapped compiler will be installed')
        config = cfg.get('config')
        config['install_missing_compilers'] = True
        cfg.set('config', config)
    elif compiler_action == 'FIND_ANY':
        tty.debug('Just find any available compiler')
        find_args = ['find']
        if scope:
            find_args.extend(['--scope', scope])
        output = spack_compiler(*find_args)
        tty.debug('spack compiler find')
        tty.debug(output)
        output = spack_compiler('list')
        tty.debug('spack compiler list')
        tty.debug(output)
    else:
        tty.debug('No compiler action to be taken')

    return None


def get_concrete_specs(root_spec, job_name, related_builds, compiler_action):
    spec_map = {
        'root': None,
        'deps': {},
    }

    if compiler_action == 'FIND_ANY':
        # This corresponds to a bootstrapping phase where we need to
        # rely on any available compiler to build the package (i.e. the
        # compiler needed to be stripped from the spec when we generated
        # the job), and thus we need to concretize the root spec again.
        tty.debug('About to concretize {0}'.format(root_spec))
        concrete_root = Spec(root_spec).concretized()
        tty.debug('Resulting concrete root: {0}'.format(concrete_root))
    else:
        # in this case, either we're relying on Spack to install missing
        # compiler bootstrapped in a previous phase, or else we only had one
        # phase (like a site which already knows what compilers are available
        # on it's runners), so we don't want to concretize that root spec
        # again.  The reason we take this path in the first case (bootstrapped
        # compiler), is that we can't concretize a spec at this point if we're
        # going to ask spack to "install_missing_compilers".
        concrete_root = Spec.from_yaml(
            str(zlib.decompress(base64.b64decode(root_spec)).decode('utf-8')))

    spec_map['root'] = concrete_root
    spec_map[job_name] = concrete_root[job_name]

    if related_builds:
        for dep_job_name in related_builds.split(';'):
            spec_map['deps'][dep_job_name] = concrete_root[dep_job_name]

    return spec_map


def register_cdash_build(build_name, base_url, project, site, track):
    url = base_url + '/api/v1/addBuild.php'
    time_stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M')
    build_stamp = '{0}-{1}'.format(time_stamp, track)
    payload = {
        "project": project,
        "site": site,
        "name": build_name,
        "stamp": build_stamp,
    }

    tty.debug('Registering cdash build to {0}, payload:'.format(url))
    tty.debug(payload)

    enc_data = json.dumps(payload).encode('utf-8')

    headers = {
        'Content-Type': 'application/json',
    }

    opener = build_opener(HTTPHandler)

    request = Request(url, data=enc_data, headers=headers)

    response = opener.open(request)
    response_code = response.getcode()

    if response_code != 200 and response_code != 201:
        msg = 'Adding build failed (response code = {0}'.format(response_code)
        raise SpackError(msg)

    response_text = response.read()
    response_json = json.loads(response_text)
    build_id = response_json['buildid']

    return (build_id, build_stamp)


def relate_cdash_builds(spec_map, cdash_base_url, job_build_id, cdash_project,
                        cdashids_mirror_url):
    if not job_build_id:
        return

    dep_map = spec_map['deps']

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    cdash_api_url = '{0}/api/v1/relateBuilds.php'.format(cdash_base_url)

    for dep_pkg_name in dep_map:
        tty.debug('Fetching cdashid file for {0}'.format(dep_pkg_name))
        dep_spec = dep_map[dep_pkg_name]
        dep_build_id = read_cdashid_from_mirror(dep_spec, cdashids_mirror_url)

        payload = {
            "project": cdash_project,
            "buildid": job_build_id,
            "relatedid": dep_build_id,
            "relationship": "depends on"
        }

        enc_data = json.dumps(payload).encode('utf-8')

        opener = build_opener(HTTPHandler)

        request = Request(cdash_api_url, data=enc_data, headers=headers)

        response = opener.open(request)
        response_code = response.getcode()

        if response_code != 200 and response_code != 201:
            msg = 'Relate builds ({0} -> {1}) failed (resp code = {2})'.format(
                job_build_id, dep_build_id, response_code)
            raise SpackError(msg)

        response_text = response.read()
        tty.debug('Relate builds response: {0}'.format(response_text))


def write_cdashid_to_mirror(cdashid, spec, mirror_url):
    if not spec.concrete:
        tty.die('Can only write cdashid for concrete spec to mirror')

    with TemporaryDirectory() as tmpdir:
        local_cdash_path = os.path.join(tmpdir, 'job.cdashid')
        with open(local_cdash_path, 'w') as fd:
            fd.write(cdashid)

        buildcache_name = bindist.tarball_name(spec, '')
        cdashid_file_name = '{0}.cdashid'.format(buildcache_name)
        remote_url = os.path.join(
            mirror_url, bindist.build_cache_relative_path(), cdashid_file_name)

        tty.debug('pushing cdashid to url')
        tty.debug('  local file path: {0}'.format(local_cdash_path))
        tty.debug('  remote url: {0}'.format(remote_url))
        web_util.push_to_url(local_cdash_path, remote_url)


def read_cdashid_from_mirror(spec, mirror_url):
    if not spec.concrete:
        tty.die('Can only read cdashid for concrete spec from mirror')

    buildcache_name = bindist.tarball_name(spec, '')
    cdashid_file_name = '{0}.cdashid'.format(buildcache_name)
    url = os.path.join(
        mirror_url, bindist.build_cache_relative_path(), cdashid_file_name)

    resp_url, resp_headers, response = web_util.read_from_url(url)
    contents = response.fp.read()

    return int(contents)


def push_mirror_contents(env, spec, yaml_path, mirror_url, build_id):
    if mirror_url:
        tty.debug('Creating buildcache')
        buildcache._createtarball(env, yaml_path, None, True, False,
                                  mirror_url, None, True, False, False, True,
                                  False)
        if build_id:
            tty.debug('Writing cdashid ({0}) to remote mirror: {1}'.format(
                build_id, mirror_url))
            write_cdashid_to_mirror(build_id, spec, mirror_url)


def copy_stage_logs_to_artifacts(job_spec, job_log_dir):
    try:
        job_pkg = spack.repo.get(job_spec)
        tty.debug('job package: {0}'.format(job_pkg))
        stage_dir = job_pkg.stage.path
        tty.debug('stage dir: {0}'.format(stage_dir))
        build_env_src = os.path.join(stage_dir, 'spack-build-env.txt')
        build_out_src = os.path.join(stage_dir, 'spack-build-out.txt')
        build_env_dst = os.path.join(
            job_log_dir, 'spack-build-env.txt')
        build_out_dst = os.path.join(
            job_log_dir, 'spack-build-out.txt')
        tty.debug('Copying logs to artifacts:')
        tty.debug('  1: {0} -> {1}'.format(
            build_env_src, build_env_dst))
        shutil.copyfile(build_env_src, build_env_dst)
        tty.debug('  2: {0} -> {1}'.format(
            build_out_src, build_out_dst))
        shutil.copyfile(build_out_src, build_out_dst)
    except Exception as inst:
        msg = ('Unable to copy build logs from stage to artifacts '
               'due to exception: {0}').format(inst)
        tty.error(msg)
