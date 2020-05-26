# Copyright 2013-2020 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import collections
import os
import re
import sys
import shutil
import copy
import socket

import six

from ordereddict_backport import OrderedDict

import llnl.util.filesystem as fs
import llnl.util.tty as tty
from llnl.util.tty.color import colorize

import spack.concretize
import spack.error
import spack.hash_types as ht
import spack.repo
import spack.schema.env
import spack.spec
import spack.store
import spack.util.spack_json as sjson
import spack.util.spack_yaml as syaml
import spack.config
import spack.user_environment as uenv
from spack.filesystem_view import YamlFilesystemView
import spack.util.environment
import spack.architecture as architecture
from spack.spec import Spec
from spack.spec_list import SpecList, InvalidSpecConstraintError
from spack.variant import UnknownVariantError
import spack.util.lock as lk

#: environment variable used to indicate the active environment
spack_env_var = 'SPACK_ENV'


#: currently activated environment
_active_environment = None


#: path where environments are stored in the spack tree
env_path = os.path.join(spack.paths.var_path, 'environments')


#: Name of the input yaml file for an environment
manifest_name = 'spack.yaml'


#: Name of the input yaml file for an environment
lockfile_name = 'spack.lock'


#: Name of the directory where environments store repos, logs, views
env_subdir_name = '.spack-env'


#: default spack.yaml file to put in new environments
default_manifest_yaml = """\
# This is a Spack Environment file.
#
# It describes a set of packages to be installed, along with
# configuration settings.
spack:
  # add package specs to the `specs` list
  specs: []
  view: true
"""
#: regex for validating enviroment names
valid_environment_name_re = r'^\w[\w-]*$'

#: version of the lockfile format. Must increase monotonically.
lockfile_format_version = 2

#: legal first keys in the spack.yaml manifest file
env_schema_keys = ('spack', 'env')

# Magic names
# The name of the standalone spec list in the manifest yaml
user_speclist_name = 'specs'
# The name of the default view (the view loaded on env.activate)
default_view_name = 'default'
# Default behavior to link all packages into views (vs. only root packages)
default_view_link = 'all'


def valid_env_name(name):
    return re.match(valid_environment_name_re, name)


def validate_env_name(name):
    if not valid_env_name(name):
        raise ValueError((
            "'%s': names must start with a letter, and only contain "
            "letters, numbers, _, and -.") % name)
    return name


def activate(
    env, use_env_repo=False, add_view=True, shell='sh', prompt=None
):
    """Activate an environment.

    To activate an environment, we add its configuration scope to the
    existing Spack configuration, and we set active to the current
    environment.

    Arguments:
        env (Environment): the environment to activate
        use_env_repo (bool): use the packages exactly as they appear in the
            environment's repository
        add_view (bool): generate commands to add view to path variables
        shell (string): One of `sh`, `csh`.
        prompt (string): string to add to the users prompt, or None

    Returns:
        cmds: Shell commands to activate environment.
    TODO: environment to use the activated spack environment.
    """
    global _active_environment

    _active_environment = env
    prepare_config_scope(_active_environment)
    if use_env_repo:
        spack.repo.path.put_first(_active_environment.repo)

    tty.debug("Using environmennt '%s'" % _active_environment.name)

    # Construct the commands to run
    cmds = ''
    if shell == 'csh':
        # TODO: figure out how to make color work for csh
        cmds += 'setenv SPACK_ENV %s;\n' % env.path
        cmds += 'alias despacktivate "spack env deactivate";\n'
        if prompt:
            cmds += 'if (! $?SPACK_OLD_PROMPT ) '
            cmds += 'setenv SPACK_OLD_PROMPT "${prompt}";\n'
            cmds += 'set prompt="%s ${prompt}";\n' % prompt
    else:
        if os.getenv('TERM') and 'color' in os.getenv('TERM') and prompt:
            prompt = colorize('@G{%s} ' % prompt, color=True)

        cmds += 'export SPACK_ENV=%s;\n' % env.path
        cmds += "alias despacktivate='spack env deactivate';\n"
        if prompt:
            cmds += 'if [ -z ${SPACK_OLD_PS1+x} ]; then\n'
            cmds += '    if [ -z ${PS1+x} ]; then\n'
            cmds += "        PS1='$$$$';\n"
            cmds += '    fi;\n'
            cmds += '    export SPACK_OLD_PS1="${PS1}";\n'
            cmds += 'fi;\n'
            cmds += 'export PS1="%s ${PS1}";\n' % prompt

    if add_view and default_view_name in env.views:
        with spack.store.db.read_transaction():
            cmds += env.add_default_view_to_shell(shell)

    return cmds


def deactivate(shell='sh'):
    """Undo any configuration or repo settings modified by ``activate()``.

    Arguments:
        shell (string): One of `sh`, `csh`. Shell style to use.

    Returns:
        (string): shell commands for `shell` to undo environment variables

    """
    global _active_environment

    if not _active_environment:
        return

    deactivate_config_scope(_active_environment)

    # use _repo so we only remove if a repo was actually constructed
    if _active_environment._repo:
        spack.repo.path.remove(_active_environment._repo)

    cmds = ''
    if shell == 'csh':
        cmds += 'unsetenv SPACK_ENV;\n'
        cmds += 'if ( $?SPACK_OLD_PROMPT ) '
        cmds += 'set prompt="$SPACK_OLD_PROMPT" && '
        cmds += 'unsetenv SPACK_OLD_PROMPT;\n'
        cmds += 'unalias despacktivate;\n'
    else:
        cmds += 'if [ ! -z ${SPACK_ENV+x} ]; then\n'
        cmds += 'unset SPACK_ENV; export SPACK_ENV;\n'
        cmds += 'fi;\n'
        cmds += 'unalias despacktivate;\n'
        cmds += 'if [ ! -z ${SPACK_OLD_PS1+x} ]; then\n'
        cmds += '    if [ "$SPACK_OLD_PS1" = \'$$$$\' ]; then\n'
        cmds += '        unset PS1; export PS1;\n'
        cmds += '    else\n'
        cmds += '        export PS1="$SPACK_OLD_PS1";\n'
        cmds += '    fi;\n'
        cmds += '    unset SPACK_OLD_PS1; export SPACK_OLD_PS1;\n'
        cmds += 'fi;\n'

    if default_view_name in _active_environment.views:
        with spack.store.db.read_transaction():
            cmds += _active_environment.rm_default_view_from_shell(shell)

    tty.debug("Deactivated environmennt '%s'" % _active_environment.name)
    _active_environment = None

    return cmds


def find_environment(args):
    """Find active environment from args, spack.yaml, or environment variable.

    This is called in ``spack.main`` to figure out which environment to
    activate.

    Check for an environment in this order:
        1. via ``spack -e ENV`` or ``spack -D DIR`` (arguments)
        2. as a spack.yaml file in the current directory, or
        3. via a path in the SPACK_ENV environment variable.

    If an environment is found, read it in.  If not, return None.

    Arguments:
        args (Namespace): argparse namespace wtih command arguments

    Returns:
        (Environment): a found environment, or ``None``
    """
    # try arguments
    env = getattr(args, 'env', None)

    # treat env as a name
    if env:
        if exists(env):
            return read(env)

    else:
        # if env was specified, see if it is a dirctory otherwise, look
        # at env_dir (env and env_dir are mutually exclusive)
        env = getattr(args, 'env_dir', None)

        # if no argument, look for a manifest file
        if not env:
            if os.path.exists(manifest_name):
                env = os.getcwd()

            # if no env, env_dir, or manifest try the environment
            if not env:
                env = os.environ.get(spack_env_var)

                # nothing was set; there's no active environment
                if not env:
                    return None

    # if we get here, env isn't the name of a spack environment; it has
    # to be a path to an environment, or there is something wrong.
    if is_env_dir(env):
        return Environment(env)

    raise SpackEnvironmentError('no environment in %s' % env)


def get_env(args, cmd_name, required=False):
    """Used by commands to get the active environment.

    This first checks for an ``env`` argument, then looks at the
    ``active`` environment.  We check args first because Spack's
    subcommand arguments are parsed *after* the ``-e`` and ``-D``
    arguments to ``spack``.  So there may be an ``env`` argument that is
    *not* the active environment, and we give it precedence.

    This is used by a number of commands for determining whether there is
    an active environment.

    If an environment is not found *and* is required, print an error
    message that says the calling command *needs* an active environment.

    Arguments:
        args (Namespace): argparse namespace wtih command arguments
        cmd_name (str): name of calling command
        required (bool): if ``True``, raise an exception when no environment
            is found; if ``False``, just return ``None``

    Returns:
        (Environment): if there is an arg or active environment
    """
    # try argument first
    env = getattr(args, 'env', None)
    if env:
        if exists(env):
            return read(env)
        elif is_env_dir(env):
            return Environment(env)
        else:
            raise SpackEnvironmentError('no environment in %s' % env)

    # try the active environment. This is set by find_environment() (above)
    if _active_environment:
        return _active_environment
    elif not required:
        return None
    else:
        tty.die(
            '`spack %s` requires an environment' % cmd_name,
            'activate an environment first:',
            '    spack env activate ENV',
            'or use:',
            '    spack -e ENV %s ...' % cmd_name)


def _root(name):
    """Non-validating version of root(), to be used internally."""
    return os.path.join(env_path, name)


def root(name):
    """Get the root directory for an environment by name."""
    validate_env_name(name)
    return _root(name)


def exists(name):
    """Whether an environment with this name exists or not."""
    if not valid_env_name(name):
        return False
    return os.path.isdir(root(name))


def active(name):
    """True if the named environment is active."""
    return _active_environment and name == _active_environment.name


def is_env_dir(path):
    """Whether a directory contains a spack environment."""
    return os.path.isdir(path) and os.path.exists(
        os.path.join(path, manifest_name))


def read(name):
    """Get an environment with the supplied name."""
    validate_env_name(name)
    if not exists(name):
        raise SpackEnvironmentError("no such environment '%s'" % name)
    return Environment(root(name))


def create(name, init_file=None, with_view=None):
    """Create a named environment in Spack."""
    validate_env_name(name)
    if exists(name):
        raise SpackEnvironmentError("'%s': environment already exists" % name)
    return Environment(root(name), init_file, with_view)


def config_dict(yaml_data):
    """Get the configuration scope section out of an spack.yaml"""
    key = spack.config.first_existing(yaml_data, env_schema_keys)
    return yaml_data[key]


def all_environment_names():
    """List the names of environments that currently exist."""
    # just return empty if the env path does not exist.  A read-only
    # operation like list should not try to create a directory.
    if not os.path.exists(env_path):
        return []

    candidates = sorted(os.listdir(env_path))
    names = []
    for candidate in candidates:
        yaml_path = os.path.join(_root(candidate), manifest_name)
        if valid_env_name(candidate) and os.path.exists(yaml_path):
            names.append(candidate)
    return names


def all_environments():
    """Generator for all named Environments."""
    for name in all_environment_names():
        yield read(name)


def validate(data, filename=None):
    # validating changes data by adding defaults. Return validated data
    validate_data = copy.deepcopy(data)
    # HACK to fully copy ruamel CommentedMap that doesn't provide copy method
    import ruamel.yaml as yaml
    setattr(
        validate_data,
        yaml.comments.Comment.attrib,
        getattr(data, yaml.comments.Comment.attrib, yaml.comments.Comment())
    )

    import jsonschema
    try:
        spack.schema.Validator(spack.schema.env.schema).validate(validate_data)
    except jsonschema.ValidationError as e:
        if hasattr(e.instance, 'lc'):
            line_number = e.instance.lc.line + 1
        else:
            line_number = None
        raise spack.config.ConfigFormatError(
            e, data, filename, line_number)
    return validate_data


def _read_yaml(str_or_file):
    """Read YAML from a file for round-trip parsing."""
    data = syaml.load_config(str_or_file)
    filename = getattr(str_or_file, 'name', None)
    default_data = validate(data, filename)
    return (data, default_data)


def _write_yaml(data, str_or_file):
    """Write YAML to a file preserving comments and dict order."""
    filename = getattr(str_or_file, 'name', None)
    validate(data, filename)
    syaml.dump_config(data, str_or_file, default_flow_style=False)


def _eval_conditional(string):
    """Evaluate conditional definitions using restricted variable scope."""
    arch = architecture.Arch(
        architecture.platform(), 'default_os', 'default_target')
    valid_variables = {
        'target': str(arch.target),
        'os': str(arch.os),
        'platform': str(arch.platform),
        'arch': str(arch),
        'architecture': str(arch),
        're': re,
        'env': os.environ,
        'hostname': socket.gethostname()
    }

    return eval(string, valid_variables)


class ViewDescriptor(object):
    def __init__(self, root, projections={}, select=[], exclude=[],
                 link=default_view_link):
        self.root = root
        self.projections = projections
        self.select = select
        self.select_fn = lambda x: any(x.satisfies(s) for s in self.select)
        self.exclude = exclude
        self.exclude_fn = lambda x: not any(x.satisfies(e)
                                            for e in self.exclude)
        self.link = link

    def __eq__(self, other):
        return all([self.root == other.root,
                    self.projections == other.projections,
                    self.select == other.select,
                    self.exclude == other.exclude,
                    self.link == other.link])

    def to_dict(self):
        ret = {'root': self.root}
        if self.projections:
            ret['projections'] = self.projections
        if self.select:
            ret['select'] = self.select
        if self.exclude:
            ret['exclude'] = self.exclude
        if self.link != default_view_link:
            ret['link'] = self.link
        return ret

    @staticmethod
    def from_dict(d):
        return ViewDescriptor(d['root'],
                              d.get('projections', {}),
                              d.get('select', []),
                              d.get('exclude', []),
                              d.get('link', default_view_link))

    def view(self):
        return YamlFilesystemView(self.root, spack.store.layout,
                                  ignore_conflicts=True,
                                  projections=self.projections)

    def __contains__(self, spec):
        """Is the spec described by the view descriptor

        Note: This does not claim the spec is already linked in the view.
        It merely checks that the spec is selected if a select operation is
        specified and is not excluded if an exclude operator is specified.
        """
        if self.select:
            if not self.select_fn(spec):
                return False

        if self.exclude:
            if not self.exclude_fn(spec):
                return False

        return True

    def regenerate(self, all_specs, roots):
        specs_for_view = []
        specs = all_specs if self.link == 'all' else roots
        for spec in specs:
            # The view does not store build deps, so if we want it to
            # recognize environment specs (which do store build deps),
            # then they need to be stripped.
            if spec.concrete:  # Do not link unconcretized roots
                # We preserve _hash _normal to avoid recomputing DAG
                # hashes (DAG hashes don't consider build deps)
                spec_copy = spec.copy(deps=('link', 'run'))
                spec_copy._hash = spec._hash
                spec_copy._normal = spec._normal
                specs_for_view.append(spec_copy)

        # regeneration queries the database quite a bit; this read
        # transaction ensures that we don't repeatedly lock/unlock.
        with spack.store.db.read_transaction():
            installed_specs_for_view = set(
                s for s in specs_for_view if s in self and s.package.installed)

            view = self.view()

            view.clean()
            specs_in_view = set(view.get_all_specs())
            tty.msg("Updating view at {0}".format(self.root))

            rm_specs = specs_in_view - installed_specs_for_view
            add_specs = installed_specs_for_view - specs_in_view

            # pass all_specs in, as it's expensive to read all the
            # spec.yaml files twice.
            view.remove_specs(*rm_specs, with_dependents=False,
                              all_specs=specs_in_view)
            view.add_specs(*add_specs, with_dependencies=False)


class Environment(object):
    def __init__(self, path, init_file=None, with_view=None):
        """Create a new environment.

        The environment can be optionally initialized with either a
        spack.yaml or spack.lock file.

        Arguments:
            path (str): path to the root directory of this environment
            init_file (str or file object): filename or file object to
                initialize the environment
            with_view (str or bool): whether a view should be maintained for
                the environment. If the value is a string, it specifies the
                path to the view.
        """
        self.path = os.path.abspath(path)

        self.txlock = lk.Lock(self._transaction_lock_path)

        # This attribute will be set properly from configuration
        # during concretization
        self.concretization = None
        self.clear()

        if init_file:
            # If we are creating the environment from an init file, we don't
            # need to lock, because there are no Spack operations that alter
            # the init file.
            with fs.open_if_filename(init_file) as f:
                if hasattr(f, 'name') and f.name.endswith('.lock'):
                    self._read_manifest(default_manifest_yaml)
                    self._read_lockfile(f)
                    self._set_user_specs_from_lockfile()
                else:
                    self._read_manifest(f, raw_yaml=default_manifest_yaml)
        else:
            with lk.ReadTransaction(self.txlock):
                self._read()

        if with_view is False:
            self.views = {}
        elif with_view is True:
            self.views = {
                default_view_name: ViewDescriptor(self.view_path_default)}
        elif isinstance(with_view, six.string_types):
            self.views = {default_view_name: ViewDescriptor(with_view)}
        # If with_view is None, then defer to the view settings determined by
        # the manifest file

    def _re_read(self):
        """Reinitialize the environment object if it has been written (this
           may not be true if the environment was just created in this running
           instance of Spack)."""
        if not os.path.exists(self.manifest_path):
            return

        self.clear()
        self._read()

    def _read(self):
        default_manifest = not os.path.exists(self.manifest_path)
        if default_manifest:
            # No manifest, use default yaml
            self._read_manifest(default_manifest_yaml)
        else:
            with open(self.manifest_path) as f:
                self._read_manifest(f)

        if os.path.exists(self.lock_path):
            with open(self.lock_path) as f:
                read_lock_version = self._read_lockfile(f)
            if default_manifest:
                # No manifest, set user specs from lockfile
                self._set_user_specs_from_lockfile()

            if read_lock_version == 1:
                tty.debug(
                    "Storing backup of old lockfile {0} at {1}".format(
                        self.lock_path, self._lock_backup_v1_path))
                shutil.copy(self.lock_path, self._lock_backup_v1_path)

    def write_transaction(self):
        """Get a write lock context manager for use in a `with` block."""
        return lk.WriteTransaction(self.txlock, acquire=self._re_read)

    def _read_manifest(self, f, raw_yaml=None):
        """Read manifest file and set up user specs."""
        if raw_yaml:
            _, self.yaml = _read_yaml(f)
            self.raw_yaml, _ = _read_yaml(raw_yaml)
        else:
            self.raw_yaml, self.yaml = _read_yaml(f)

        self.spec_lists = OrderedDict()

        for item in config_dict(self.yaml).get('definitions', []):
            entry = copy.deepcopy(item)
            when = _eval_conditional(entry.pop('when', 'True'))
            assert len(entry) == 1
            if when:
                name, spec_list = next(iter(entry.items()))
                user_specs = SpecList(name, spec_list, self.spec_lists.copy())
                if name in self.spec_lists:
                    self.spec_lists[name].extend(user_specs)
                else:
                    self.spec_lists[name] = user_specs

        spec_list = config_dict(self.yaml).get(user_speclist_name)
        user_specs = SpecList(user_speclist_name, [s for s in spec_list if s],
                              self.spec_lists.copy())
        self.spec_lists[user_speclist_name] = user_specs

        enable_view = config_dict(self.yaml).get('view')
        # enable_view can be boolean, string, or None
        if enable_view is True or enable_view is None:
            self.views = {
                default_view_name: ViewDescriptor(self.view_path_default)}
        elif isinstance(enable_view, six.string_types):
            self.views = {default_view_name: ViewDescriptor(enable_view)}
        elif enable_view:
            self.views = dict((name, ViewDescriptor.from_dict(values))
                              for name, values in enable_view.items())
        else:
            self.views = {}
        # Retrieve the current concretization strategy
        configuration = config_dict(self.yaml)
        self.concretization = configuration.get('concretization')

    @property
    def user_specs(self):
        return self.spec_lists[user_speclist_name]

    def _set_user_specs_from_lockfile(self):
        """Copy user_specs from a read-in lockfile."""
        self.spec_lists = {
            user_speclist_name: SpecList(
                user_speclist_name,
                [str(s) for s in self.concretized_user_specs]
            )
        }

    def clear(self):
        self.spec_lists = {user_speclist_name: SpecList()}  # specs from yaml
        self.concretized_user_specs = []  # user specs from last concretize
        self.concretized_order = []       # roots of last concretize, in order
        self.specs_by_hash = {}           # concretized specs by hash
        self.new_specs = []               # write packages for these on write()
        self._repo = None                 # RepoPath for this env (memoized)
        self._previous_active = None      # previously active environment

    @property
    def internal(self):
        """Whether this environment is managed by Spack."""
        return self.path.startswith(env_path)

    @property
    def name(self):
        """Human-readable representation of the environment.

        This is the path for directory environments, and just the name
        for named environments.
        """
        if self.internal:
            return os.path.basename(self.path)
        else:
            return self.path

    @property
    def active(self):
        """True if this environment is currently active."""
        return _active_environment and self.path == _active_environment.path

    @property
    def manifest_path(self):
        """Path to spack.yaml file in this environment."""
        return os.path.join(self.path, manifest_name)

    @property
    def _transaction_lock_path(self):
        """The location of the lock file used to synchronize multiple
        processes updating the same environment.
        """
        return os.path.join(self.env_subdir_path, 'transaction_lock')

    @property
    def lock_path(self):
        """Path to spack.lock file in this environment."""
        return os.path.join(self.path, lockfile_name)

    @property
    def _lock_backup_v1_path(self):
        """Path to backup of v1 lockfile before conversion to v2"""
        return self.lock_path + '.backup.v1'

    @property
    def env_subdir_path(self):
        """Path to directory where the env stores repos, logs, views."""
        return os.path.join(self.path, env_subdir_name)

    @property
    def repos_path(self):
        return os.path.join(self.path, env_subdir_name, 'repos')

    @property
    def log_path(self):
        return os.path.join(self.path, env_subdir_name, 'logs')

    @property
    def view_path_default(self):
        # default path for environment views
        return os.path.join(self.env_subdir_path, 'view')

    @property
    def repo(self):
        if self._repo is None:
            self._repo = make_repo_path(self.repos_path)
        return self._repo

    def included_config_scopes(self):
        """List of included configuration scopes from the environment.

        Scopes are listed in the YAML file in order from highest to
        lowest precedence, so configuration from earlier scope will take
        precedence over later ones.

        This routine returns them in the order they should be pushed onto
        the internal scope stack (so, in reverse, from lowest to highest).
        """
        scopes = []

        # load config scopes added via 'include:', in reverse so that
        # highest-precedence scopes are last.
        includes = config_dict(self.yaml).get('include', [])
        for i, config_path in enumerate(reversed(includes)):
            # allow paths to contain environment variables
            config_path = config_path.format(**os.environ)

            # treat relative paths as relative to the environment
            if not os.path.isabs(config_path):
                config_path = os.path.join(self.path, config_path)
                config_path = os.path.normpath(os.path.realpath(config_path))

            if os.path.isdir(config_path):
                # directories are treated as regular ConfigScopes
                config_name = 'env:%s:%s' % (
                    self.name, os.path.basename(config_path))
                scope = spack.config.ConfigScope(config_name, config_path)
            else:
                # files are assumed to be SingleFileScopes
                base, ext = os.path.splitext(os.path.basename(config_path))
                config_name = 'env:%s:%s' % (self.name, base)
                scope = spack.config.SingleFileScope(
                    config_name, config_path, spack.schema.merged.schema)

            scopes.append(scope)

        return scopes

    def env_file_config_scope_name(self):
        """Name of the config scope of this environment's manifest file."""
        return 'env:%s' % self.name

    def env_file_config_scope(self):
        """Get the configuration scope for the environment's manifest file."""
        config_name = self.env_file_config_scope_name()
        return spack.config.SingleFileScope(config_name,
                                            self.manifest_path,
                                            spack.schema.env.schema,
                                            [env_schema_keys])

    def config_scopes(self):
        """A list of all configuration scopes for this environment."""
        return self.included_config_scopes() + [self.env_file_config_scope()]

    def destroy(self):
        """Remove this environment from Spack entirely."""
        shutil.rmtree(self.path)

    def update_stale_references(self, from_list=None):
        """Iterate over spec lists updating references."""
        if not from_list:
            from_list = next(iter(self.spec_lists.keys()))
        index = list(self.spec_lists.keys()).index(from_list)

        # spec_lists is an OrderedDict, all list entries after the modified
        # list may refer to the modified list. Update stale references
        for i, (name, speclist) in enumerate(
            list(self.spec_lists.items())[index + 1:], index + 1
        ):
            new_reference = dict((n, self.spec_lists[n])
                                 for n in list(self.spec_lists.keys())[:i])
            speclist.update_reference(new_reference)

    def add(self, user_spec, list_name=user_speclist_name):
        """Add a single user_spec (non-concretized) to the Environment

        Returns:
            (bool): True if the spec was added, False if it was already
                present and did not need to be added

        """
        spec = Spec(user_spec)

        if list_name not in self.spec_lists:
            raise SpackEnvironmentError(
                'No list %s exists in environment %s' % (list_name, self.name)
            )

        if list_name == user_speclist_name:
            if not spec.name:
                raise SpackEnvironmentError(
                    'cannot add anonymous specs to an environment!')
            elif not spack.repo.path.exists(spec.name):
                virtuals = spack.repo.path.provider_index.providers.keys()
                if spec.name not in virtuals:
                    msg = 'no such package: %s' % spec.name
                    raise SpackEnvironmentError(msg)

        list_to_change = self.spec_lists[list_name]
        existing = str(spec) in list_to_change.yaml_list
        if not existing:
            list_to_change.add(str(spec))
            self.update_stale_references(list_name)

        return bool(not existing)

    def remove(self, query_spec, list_name=user_speclist_name, force=False):
        """Remove specs from an environment that match a query_spec"""
        query_spec = Spec(query_spec)

        list_to_change = self.spec_lists[list_name]
        matches = []

        if not query_spec.concrete:
            matches = [s for s in list_to_change if s.satisfies(query_spec)]

        if not matches:
            # concrete specs match against concrete specs in the env
            # by *dag hash*, not build hash.
            dag_hashes_in_order = [
                self.specs_by_hash[build_hash].dag_hash()
                for build_hash in self.concretized_order
            ]

            specs_hashes = zip(
                self.concretized_user_specs, dag_hashes_in_order
            )

            matches = [
                s for s, h in specs_hashes
                if query_spec.dag_hash() == h
            ]

        if not matches:
            raise SpackEnvironmentError(
                "Not found: {0}".format(query_spec))

        old_specs = set(self.user_specs)
        for spec in matches:
            if spec in list_to_change:
                list_to_change.remove(spec)

        self.update_stale_references(list_name)

        # If force, update stale concretized specs
        # Only check specs removed by this operation
        new_specs = set(self.user_specs)
        for spec in old_specs - new_specs:
            if force and spec in self.concretized_user_specs:
                i = self.concretized_user_specs.index(spec)
                del self.concretized_user_specs[i]

                dag_hash = self.concretized_order[i]
                del self.concretized_order[i]
                del self.specs_by_hash[dag_hash]

    def concretize(self, force=False):
        """Concretize user_specs in this environment.

        Only concretizes specs that haven't been concretized yet unless
        force is ``True``.

        This only modifies the environment in memory. ``write()`` will
        write out a lockfile containing concretized specs.

        Arguments:
            force (bool): re-concretize ALL specs, even those that were
               already concretized

        Returns:
            List of specs that have been concretized. Each entry is a tuple of
            the user spec and the corresponding concretized spec.
        """
        if force:
            # Clear previously concretized specs
            self.concretized_user_specs = []
            self.concretized_order = []
            self.specs_by_hash = {}

        # Pick the right concretization strategy
        if self.concretization == 'together':
            return self._concretize_together()
        if self.concretization == 'separately':
            return self._concretize_separately()

        msg = 'concretization strategy not implemented [{0}]'
        raise SpackEnvironmentError(msg.format(self.concretization))

    def _concretize_together(self):
        """Concretization strategy that concretizes all the specs
        in the same DAG.
        """
        # Exit early if the set of concretized specs is the set of user specs
        user_specs_did_not_change = not bool(
            set(self.user_specs) - set(self.concretized_user_specs)
        )
        if user_specs_did_not_change:
            return []

        # Check that user specs don't have duplicate packages
        counter = collections.defaultdict(int)
        for user_spec in self.user_specs:
            counter[user_spec.name] += 1

        duplicates = []
        for name, count in counter.items():
            if count > 1:
                duplicates.append(name)

        if duplicates:
            msg = ('environment that are configured to concretize specs'
                   ' together cannot contain more than one spec for each'
                   ' package [{0}]'.format(', '.join(duplicates)))
            raise SpackEnvironmentError(msg)

        # Proceed with concretization
        self.concretized_user_specs = []
        self.concretized_order = []
        self.specs_by_hash = {}

        concrete_specs = spack.concretize.concretize_specs_together(
            *self.user_specs
        )
        concretized_specs = [x for x in zip(self.user_specs, concrete_specs)]
        for abstract, concrete in concretized_specs:
            self._add_concrete_spec(abstract, concrete)
        return concretized_specs

    def _concretize_separately(self):
        """Concretization strategy that concretizes separately one
        user spec after the other.
        """
        # keep any concretized specs whose user specs are still in the manifest
        old_concretized_user_specs = self.concretized_user_specs
        old_concretized_order = self.concretized_order
        old_specs_by_hash = self.specs_by_hash

        self.concretized_user_specs = []
        self.concretized_order = []
        self.specs_by_hash = {}

        for s, h in zip(old_concretized_user_specs, old_concretized_order):
            if s in self.user_specs:
                concrete = old_specs_by_hash[h]
                self._add_concrete_spec(s, concrete, new=False)

        # Concretize any new user specs that we haven't concretized yet
        concretized_specs = []
        for uspec, uspec_constraints in zip(
                self.user_specs, self.user_specs.specs_as_constraints):
            if uspec not in old_concretized_user_specs:
                concrete = _concretize_from_constraints(uspec_constraints)
                self._add_concrete_spec(uspec, concrete)
                concretized_specs.append((uspec, concrete))
        return concretized_specs

    def concretize_and_add(self, user_spec, concrete_spec=None):
        """Concretize and add a single spec to the environment.

        Concretize the provided ``user_spec`` and add it along with the
        concretized result to the environment. If the given ``user_spec`` was
        already present in the environment, this does not add a duplicate.
        The concretized spec will be added unless the ``user_spec`` was
        already present and an associated concrete spec was already present.

        Args:
            concrete_spec: if provided, then it is assumed that it is the
                result of concretizing the provided ``user_spec``
        """
        if self.concretization == 'together':
            msg = 'cannot install a single spec in an environment that is ' \
                  'configured to be concretized together. Run instead:\n\n' \
                  '    $ spack add <spec>\n' \
                  '    $ spack install\n'
            raise SpackEnvironmentError(msg)

        spec = Spec(user_spec)

        if self.add(spec):
            concrete = concrete_spec or spec.concretized()
            self._add_concrete_spec(spec, concrete)
        else:
            # spec might be in the user_specs, but not installed.
            # TODO: Redo name-based comparison for old style envs
            spec = next(
                s for s in self.user_specs if s.satisfies(user_spec)
            )
            concrete = self.specs_by_hash.get(spec.build_hash())
            if not concrete:
                concrete = spec.concretized()
                self._add_concrete_spec(spec, concrete)

        return concrete

    @property
    def default_view(self):
        if not self.views:
            raise SpackEnvironmentError(
                "{0} does not have a view enabled".format(self.name))

        if default_view_name not in self.views:
            raise SpackEnvironmentError(
                "{0} does not have a default view enabled".format(self.name))

        return self.views[default_view_name]

    def update_default_view(self, viewpath):
        name = default_view_name
        if name in self.views and self.default_view.root != viewpath:
            shutil.rmtree(self.default_view.root)

        if viewpath:
            if name in self.views:
                self.default_view.root = viewpath
            else:
                self.views[name] = ViewDescriptor(viewpath)
        else:
            self.views.pop(name, None)

    def regenerate_views(self):
        if not self.views:
            tty.debug("Skip view update, this environment does not"
                      " maintain a view")
            return

        specs = self._get_environment_specs()
        for view in self.views.values():
            view.regenerate(specs, self.roots())

    def _env_modifications_for_default_view(self, reverse=False):
        all_mods = spack.util.environment.EnvironmentModifications()

        errors = []
        for _, spec in self.concretized_specs():
            if spec in self.default_view and spec.package.installed:
                try:
                    mods = uenv.environment_modifications_for_spec(
                        spec, self.default_view)
                except Exception as e:
                    msg = ("couldn't get environment settings for %s"
                           % spec.format("{name}@{version} /{hash:7}"))
                    errors.append((msg, str(e)))
                    continue

                all_mods.extend(mods.reversed() if reverse else mods)

        return all_mods, errors

    def add_default_view_to_shell(self, shell):
        env_mod = spack.util.environment.EnvironmentModifications()

        if default_view_name not in self.views:
            # No default view to add to shell
            return env_mod.shell_modifications(shell)

        env_mod.extend(uenv.unconditional_environment_modifications(
            self.default_view))

        mods, errors = self._env_modifications_for_default_view()
        env_mod.extend(mods)
        if errors:
            for err in errors:
                tty.warn(*err)

        # deduplicate paths from specs mapped to the same location
        for env_var in env_mod.group_by_name():
            env_mod.prune_duplicate_paths(env_var)

        return env_mod.shell_modifications(shell)

    def rm_default_view_from_shell(self, shell):
        env_mod = spack.util.environment.EnvironmentModifications()

        if default_view_name not in self.views:
            # No default view to add to shell
            return env_mod.shell_modifications(shell)

        env_mod.extend(uenv.unconditional_environment_modifications(
            self.default_view).reversed())

        mods, _ = self._env_modifications_for_default_view(reverse=True)
        env_mod.extend(mods)

        return env_mod.shell_modifications(shell)

    def _add_concrete_spec(self, spec, concrete, new=True):
        """Called when a new concretized spec is added to the environment.

        This ensures that all internal data structures are kept in sync.

        Arguments:
            spec (Spec): user spec that resulted in the concrete spec
            concrete (Spec): spec concretized within this environment
            new (bool): whether to write this spec's package to the env
                repo on write()
        """
        assert concrete.concrete

        # when a spec is newly concretized, we need to make a note so
        # that we can write its package to the env repo on write()
        if new:
            self.new_specs.append(concrete)

        # update internal lists of specs
        self.concretized_user_specs.append(spec)

        h = concrete.build_hash()
        self.concretized_order.append(h)
        self.specs_by_hash[h] = concrete

    def install(self, user_spec, concrete_spec=None, **install_args):
        """Install a single spec into an environment.

        This will automatically concretize the single spec, but it won't
        affect other as-yet unconcretized specs.
        """
        concrete = self.concretize_and_add(user_spec, concrete_spec)

        self._install(concrete, **install_args)

    def _install(self, spec, **install_args):
        # "spec" must be concrete
        spec.package.do_install(**install_args)

        if not spec.external:
            # Make sure log directory exists
            log_path = self.log_path
            fs.mkdirp(log_path)

            with fs.working_dir(self.path):
                # Link the resulting log file into logs dir
                build_log_link = os.path.join(
                    log_path, '%s-%s.log' % (spec.name, spec.dag_hash(7)))
                if os.path.lexists(build_log_link):
                    os.remove(build_log_link)
                os.symlink(spec.package.build_log_path, build_log_link)

    def install_all(self, args=None):
        """Install all concretized specs in an environment.

        Note: this does not regenerate the views for the environment;
        that needs to be done separately with a call to write().

        """

        # If "spack install" is invoked repeatedly for a large environment
        # where all specs are already installed, the operation can take
        # a large amount of time due to repeatedly acquiring and releasing
        # locks, this does an initial check across all specs within a single
        # DB read transaction to reduce time spent in this case.
        uninstalled_specs = []
        with spack.store.db.read_transaction():
            for concretized_hash in self.concretized_order:
                spec = self.specs_by_hash[concretized_hash]
                if not spec.package.installed:
                    uninstalled_specs.append(spec)

        for spec in uninstalled_specs:
            # Parse cli arguments and construct a dictionary
            # that will be passed to Package.do_install API
            kwargs = dict()
            if args:
                spack.cmd.install.update_kwargs_from_args(args, kwargs)

            self._install(spec, **kwargs)

    def all_specs_by_hash(self):
        """Map of hashes to spec for all specs in this environment."""
        # Note this uses dag-hashes calculated without build deps as keys,
        # whereas the environment tracks specs based on dag-hashes calculated
        # with all dependencies. This function should not be used by an
        # Environment object for management of its own data structures
        hashes = {}
        for h in self.concretized_order:
            specs = self.specs_by_hash[h].traverse(deptype=('link', 'run'))
            for spec in specs:
                hashes[spec.dag_hash()] = spec
        return hashes

    def all_specs(self):
        """Return all specs, even those a user spec would shadow."""
        return sorted(self.all_specs_by_hash().values())

    def all_hashes(self):
        """Return all specs, even those a user spec would shadow."""
        return list(self.all_specs_by_hash().keys())

    def roots(self):
        """Specs explicitly requested by the user *in this environment*.

        Yields both added and installed specs that have user specs in
        `spack.yaml`.
        """
        concretized = dict(self.concretized_specs())
        for spec in self.user_specs:
            concrete = concretized.get(spec)
            yield concrete if concrete else spec

    def added_specs(self):
        """Specs that are not yet installed.

        Yields the user spec for non-concretized specs, and the concrete
        spec for already concretized but not yet installed specs.
        """
        # use a transaction to avoid overhead of repeated calls
        # to `package.installed`
        with spack.store.db.read_transaction():
            concretized = dict(self.concretized_specs())
            for spec in self.user_specs:
                concrete = concretized.get(spec)
                if not concrete:
                    yield spec
                elif not concrete.package.installed:
                    yield concrete

    def concretized_specs(self):
        """Tuples of (user spec, concrete spec) for all concrete specs."""
        for s, h in zip(self.concretized_user_specs, self.concretized_order):
            yield (s, self.specs_by_hash[h])

    def removed_specs(self):
        """Tuples of (user spec, concrete spec) for all specs that will be
           removed on nexg concretize."""
        needed = set()
        for s, c in self.concretized_specs():
            if s in self.user_specs:
                for d in c.traverse():
                    needed.add(d)

        for s, c in self.concretized_specs():
            for d in c.traverse():
                if d not in needed:
                    yield d

    def _get_environment_specs(self, recurse_dependencies=True):
        """Returns the specs of all the packages in an environment.

        If these specs appear under different user_specs, only one copy
        is added to the list returned.
        """
        spec_list = list()

        for spec_hash in self.concretized_order:
            spec = self.specs_by_hash[spec_hash]

            specs = (spec.traverse(deptype=('link', 'run'))
                     if recurse_dependencies else (spec,))

            spec_list.extend(specs)

        return spec_list

    def _to_lockfile_dict(self):
        """Create a dictionary to store a lockfile for this environment."""
        concrete_specs = {}
        for spec in self.specs_by_hash.values():
            for s in spec.traverse():
                dag_hash_all = s.build_hash()
                if dag_hash_all not in concrete_specs:
                    spec_dict = s.to_node_dict(hash=ht.build_hash)
                    spec_dict[s.name]['hash'] = s.dag_hash()
                    concrete_specs[dag_hash_all] = spec_dict

        hash_spec_list = zip(
            self.concretized_order, self.concretized_user_specs)

        # this is the lockfile we'll write out
        data = {
            # metadata about the format
            '_meta': {
                'file-type': 'spack-lockfile',
                'lockfile-version': lockfile_format_version,
            },

            # users specs + hashes are the 'roots' of the environment
            'roots': [{
                'hash': h,
                'spec': str(s)
            } for h, s in hash_spec_list],

            # Concrete specs by hash, including dependencies
            'concrete_specs': concrete_specs,
        }

        return data

    def _read_lockfile(self, file_or_json):
        """Read a lockfile from a file or from a raw string."""
        lockfile_dict = sjson.load(file_or_json)
        self._read_lockfile_dict(lockfile_dict)
        return lockfile_dict['_meta']['lockfile-version']

    def _read_lockfile_dict(self, d):
        """Read a lockfile dictionary into this environment."""
        roots = d['roots']
        self.concretized_user_specs = [Spec(r['spec']) for r in roots]
        self.concretized_order = [r['hash'] for r in roots]

        json_specs_by_hash = d['concrete_specs']
        root_hashes = set(self.concretized_order)

        specs_by_hash = {}
        for dag_hash, node_dict in json_specs_by_hash.items():
            specs_by_hash[dag_hash] = Spec.from_node_dict(node_dict)

        for dag_hash, node_dict in json_specs_by_hash.items():
            for dep_name, dep_hash, deptypes in (
                    Spec.dependencies_from_node_dict(node_dict)):
                specs_by_hash[dag_hash]._add_dependency(
                    specs_by_hash[dep_hash], deptypes)

        # If we are reading an older lockfile format (which uses dag hashes
        # that exclude build deps), we use this to convert the old
        # concretized_order to the full hashes (preserving the order)
        old_hash_to_new = {}
        self.specs_by_hash = {}
        for _, spec in specs_by_hash.items():
            dag_hash = spec.dag_hash()
            build_hash = spec.build_hash()
            if dag_hash in root_hashes:
                old_hash_to_new[dag_hash] = build_hash

            if (dag_hash in root_hashes or build_hash in root_hashes):
                self.specs_by_hash[build_hash] = spec

        if old_hash_to_new:
            # Replace any older hashes in concretized_order with hashes
            # that include build deps
            self.concretized_order = [
                old_hash_to_new.get(h, h) for h in self.concretized_order]

    def write(self, regenerate_views=True):
        """Writes an in-memory environment to its location on disk.

        Write out package files for each newly concretized spec.  Also
        regenerate any views associated with the environment, if
        regenerate_views is True.

        Arguments:
            regenerate_views (bool): regenerate views as well as
                writing if True.

        """
        # ensure path in var/spack/environments
        fs.mkdirp(self.path)

        yaml_dict = config_dict(self.yaml)
        raw_yaml_dict = config_dict(self.raw_yaml)

        if self.specs_by_hash:
            # ensure the prefix/.env directory exists
            fs.mkdirp(self.env_subdir_path)

            for spec in self.new_specs:
                for dep in spec.traverse():
                    if not dep.concrete:
                        raise ValueError('specs passed to environment.write() '
                                         'must be concrete!')

                    root = os.path.join(self.repos_path, dep.namespace)
                    repo = spack.repo.create_or_construct(root, dep.namespace)
                    pkg_dir = repo.dirname_for_package_name(dep.name)

                    fs.mkdirp(pkg_dir)
                    spack.repo.path.dump_provenance(dep, pkg_dir)
            self.new_specs = []

            # write the lock file last
            with fs.write_tmp_and_move(self.lock_path) as f:
                sjson.dump(self._to_lockfile_dict(), stream=f)
        else:
            if os.path.exists(self.lock_path):
                os.unlink(self.lock_path)

        # invalidate _repo cache
        self._repo = None

        # put any changes in the definitions in the YAML
        for name, speclist in self.spec_lists.items():
            if name == user_speclist_name:
                # The primary list is handled differently
                continue

            active_yaml_lists = [x for x in yaml_dict.get('definitions', [])
                                 if name in x and
                                 _eval_conditional(x.get('when', 'True'))]

            # Remove any specs in yaml that are not in internal representation
            for ayl in active_yaml_lists:
                # If it's not a string, it's a matrix. Those can't have changed
                # If it is a string that starts with '$', it's a reference.
                # Those also can't have changed.
                ayl[name][:] = [s for s in ayl.setdefault(name, [])
                                if (not isinstance(s, six.string_types)) or
                                s.startswith('$') or Spec(s) in speclist.specs]

            # Put the new specs into the first active list from the yaml
            new_specs = [entry for entry in speclist.yaml_list
                         if isinstance(entry, six.string_types) and
                         not any(entry in ayl[name]
                                 for ayl in active_yaml_lists)]
            list_for_new_specs = active_yaml_lists[0].setdefault(name, [])
            list_for_new_specs[:] = list_for_new_specs + new_specs

        # put the new user specs in the YAML.
        # This can be done directly because there can't be multiple definitions
        # nor when clauses for `specs` list.
        yaml_spec_list = yaml_dict.setdefault(user_speclist_name,
                                              [])
        yaml_spec_list[:] = self.user_specs.yaml_list

        # Construct YAML representation of view
        default_name = default_view_name
        if self.views and len(self.views) == 1 and default_name in self.views:
            path = self.default_view.root
            if self.default_view == ViewDescriptor(self.view_path_default):
                view = True
            elif self.default_view == ViewDescriptor(path):
                view = path
            else:
                view = dict((name, view.to_dict())
                            for name, view in self.views.items())
        elif self.views:
            view = dict((name, view.to_dict())
                        for name, view in self.views.items())
        else:
            view = False

        yaml_dict['view'] = view

        # Remove yaml sections that are shadowing defaults
        # construct garbage path to ensure we don't find a manifest by accident
        with fs.temp_cwd() as env_dir:
            bare_env = Environment(env_dir, with_view=self.view_path_default)
            keys_present = list(yaml_dict.keys())
            for key in keys_present:
                if yaml_dict[key] == config_dict(bare_env.yaml).get(key, None):
                    if key not in raw_yaml_dict:
                        del yaml_dict[key]

        # if all that worked, write out the manifest file at the top level
        # Only actually write if it has changed or was never written
        changed = self.yaml != self.raw_yaml
        written = os.path.exists(self.manifest_path)
        if changed or not written:
            self.raw_yaml = copy.deepcopy(self.yaml)
            with fs.write_tmp_and_move(self.manifest_path) as f:
                _write_yaml(self.yaml, f)

        # TODO: rethink where this needs to happen along with
        # writing. For some of the commands (like install, which write
        # concrete specs AND regen) this might as well be a separate
        # call.  But, having it here makes the views consistent witht the
        # concretized environment for most operations.  Which is the
        # special case?
        if regenerate_views:
            self.regenerate_views()

    def __enter__(self):
        self._previous_active = _active_environment
        activate(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        deactivate()
        if self._previous_active:
            activate(self._previous_active)


def display_specs(concretized_specs):
    """Displays the list of specs returned by `Environment.concretize()`.

    Args:
        concretized_specs (list): list of specs returned by
            `Environment.concretize()`
    """
    def _tree_to_display(spec):
        return spec.tree(
            recurse_dependencies=True,
            status_fn=spack.spec.Spec.install_status,
            hashlen=7, hashes=True)

    for user_spec, concrete_spec in concretized_specs:
        tty.msg('Concretized {0}'.format(user_spec))
        sys.stdout.write(_tree_to_display(concrete_spec))
        print('')


def _concretize_from_constraints(spec_constraints):
    # Accept only valid constraints from list and concretize spec
    # Get the named spec even if out of order
    root_spec = [s for s in spec_constraints if s.name]
    if len(root_spec) != 1:
        m = 'The constraints %s are not a valid spec ' % spec_constraints
        m += 'concretization target. all specs must have a single name '
        m += 'constraint for concretization.'
        raise InvalidSpecConstraintError(m)
    spec_constraints.remove(root_spec[0])

    invalid_constraints = []
    while True:
        # Attach all anonymous constraints to one named spec
        s = root_spec[0].copy()
        for c in spec_constraints:
            if c not in invalid_constraints:
                s.constrain(c)
        try:
            return s.concretized()
        except spack.spec.InvalidDependencyError as e:
            invalid_deps_string = ['^' + d for d in e.invalid_deps]
            invalid_deps = [c for c in spec_constraints
                            if any(c.satisfies(invd, strict=True)
                                   for invd in invalid_deps_string)]
            if len(invalid_deps) != len(invalid_deps_string):
                raise e
            invalid_constraints.extend(invalid_deps)
        except UnknownVariantError as e:
            invalid_variants = e.unknown_variants
            inv_variant_constraints = [c for c in spec_constraints
                                       if any(name in c.variants
                                              for name in invalid_variants)]
            if len(inv_variant_constraints) != len(invalid_variants):
                raise e
            invalid_constraints.extend(inv_variant_constraints)


def make_repo_path(root):
    """Make a RepoPath from the repo subdirectories in an environment."""
    path = spack.repo.RepoPath()

    if os.path.isdir(root):
        for repo_root in os.listdir(root):
            repo_root = os.path.join(root, repo_root)

            if not os.path.isdir(repo_root):
                continue

            repo = spack.repo.Repo(repo_root)
            path.put_last(repo)

    return path


def prepare_config_scope(env):
    """Add env's scope to the global configuration search path."""
    for scope in env.config_scopes():
        spack.config.config.push_scope(scope)


def deactivate_config_scope(env):
    """Remove any scopes from env from the global config path."""
    for scope in env.config_scopes():
        spack.config.config.remove_scope(scope.name)


class SpackEnvironmentError(spack.error.SpackError):
    """Superclass for all errors to do with Spack environments."""
