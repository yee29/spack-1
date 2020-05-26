.. Copyright 2013-2020 Lawrence Livermore National Security, LLC and other
   Spack Project Developers. See the top-level COPYRIGHT file for details.

   SPDX-License-Identifier: (Apache-2.0 OR MIT)

.. _modules:

=======
Modules
=======

The use of module systems to manage user environment in a controlled way
is a common practice at HPC centers that is often embraced also by individual
programmers on their development machines. To support this common practice
Spack integrates with `Environment Modules
<http://modules.sourceforge.net/>`_  and  `LMod
<http://lmod.readthedocs.io/en/latest/>`_ by
providing post-install hooks that generate module files and commands to manipulate them.

.. _shell-support:

----------------------------
Using module files via Spack
----------------------------

If you have installed a supported module system you should be able to
run either ``module avail`` or ``use -l spack`` to see what module
files have been installed.  Here is sample output of those programs,
showing lots of installed packages:

.. code-block:: console

   $ module avail

   --------------------------------------------------------------- ~/spack/share/spack/modules/linux-ubuntu14-x86_64 ---------------------------------------------------------------
   autoconf-2.69-gcc-4.8-qextxkq       hwloc-1.11.6-gcc-6.3.0-akcisez             m4-1.4.18-gcc-4.8-ev2znoc                   openblas-0.2.19-gcc-6.3.0-dhkmed6        py-setuptools-34.2.0-gcc-6.3.0-fadur4s
   automake-1.15-gcc-4.8-maqvukj       isl-0.18-gcc-4.8-afi6taq                   m4-1.4.18-gcc-6.3.0-uppywnz                 openmpi-2.1.0-gcc-6.3.0-go2s4z5          py-six-1.10.0-gcc-6.3.0-p4dhkaw
   binutils-2.28-gcc-4.8-5s7c6rs       libiconv-1.15-gcc-4.8-at46wg3              mawk-1.3.4-gcc-4.8-acjez57                  openssl-1.0.2k-gcc-4.8-dkls5tk           python-2.7.13-gcc-6.3.0-tyehea7
   bison-3.0.4-gcc-4.8-ek4luo5         libpciaccess-0.13.4-gcc-6.3.0-gmufnvh      mawk-1.3.4-gcc-6.3.0-ostdoms                openssl-1.0.2k-gcc-6.3.0-gxgr5or         readline-7.0-gcc-4.8-xhufqhn
   bzip2-1.0.6-gcc-4.8-iffrxzn         libsigsegv-2.11-gcc-4.8-pp2cvte            mpc-1.0.3-gcc-4.8-g5mztc5                   pcre-8.40-gcc-4.8-r5pbrxb                readline-7.0-gcc-6.3.0-zzcyicg
   bzip2-1.0.6-gcc-6.3.0-bequudr       libsigsegv-2.11-gcc-6.3.0-7enifnh          mpfr-3.1.5-gcc-4.8-o7xm7az                  perl-5.24.1-gcc-4.8-dg5j65u              sqlite-3.8.5-gcc-6.3.0-6zoruzj
   cmake-3.7.2-gcc-6.3.0-fowuuby       libtool-2.4.6-gcc-4.8-7a523za              mpich-3.2-gcc-6.3.0-dmvd3aw                 perl-5.24.1-gcc-6.3.0-6uzkpt6            tar-1.29-gcc-4.8-wse2ass
   curl-7.53.1-gcc-4.8-3fz46n6         libtool-2.4.6-gcc-6.3.0-n7zmbzt            ncurses-6.0-gcc-4.8-dcpe7ia                 pkg-config-0.29.2-gcc-4.8-ib33t75        tcl-8.6.6-gcc-4.8-tfxzqbr
   expat-2.2.0-gcc-4.8-mrv6bd4         libxml2-2.9.4-gcc-4.8-ryzxnsu              ncurses-6.0-gcc-6.3.0-ucbhcdy               pkg-config-0.29.2-gcc-6.3.0-jpgubk3      util-macros-1.19.1-gcc-6.3.0-xorz2x2
   flex-2.6.3-gcc-4.8-yf345oo          libxml2-2.9.4-gcc-6.3.0-rltzsdh            netlib-lapack-3.6.1-gcc-6.3.0-js33dog       py-appdirs-1.4.0-gcc-6.3.0-jxawmw7       xz-5.2.3-gcc-4.8-mew4log
   gcc-6.3.0-gcc-4.8-24puqve           lmod-7.4.1-gcc-4.8-je4srhr                 netlib-scalapack-2.0.2-gcc-6.3.0-5aidk4l    py-numpy-1.12.0-gcc-6.3.0-oemmoeu        xz-5.2.3-gcc-6.3.0-3vqeuvb
   gettext-0.19.8.1-gcc-4.8-yymghlh    lua-5.3.4-gcc-4.8-im75yaz                  netlib-scalapack-2.0.2-gcc-6.3.0-hjsemcn    py-packaging-16.8-gcc-6.3.0-i2n3dtl      zip-3.0-gcc-4.8-rwar22d
   gmp-6.1.2-gcc-4.8-5ub2wu5           lua-luafilesystem-1_6_3-gcc-4.8-wkey3nl    netlib-scalapack-2.0.2-gcc-6.3.0-jva724b    py-pyparsing-2.1.10-gcc-6.3.0-tbo6gmw    zlib-1.2.11-gcc-4.8-pgxsxv7
   help2man-1.47.4-gcc-4.8-kcnqmau     lua-luaposix-33.4.0-gcc-4.8-mdod2ry        netlib-scalapack-2.0.2-gcc-6.3.0-rgqfr6d    py-scipy-0.19.0-gcc-6.3.0-kr7nat4        zlib-1.2.11-gcc-6.3.0-7cqp6cj

The names should look familiar, as they resemble the output from ``spack find``.
You *can* use the modules here directly.  For example, you could type either of these commands
to load the ``cmake`` module:

.. code-block:: console

   $ use cmake-3.7.2-gcc-6.3.0-fowuuby

.. code-block:: console

   $ module load cmake-3.7.2-gcc-6.3.0-fowuuby

Neither of these is particularly pretty, easy to remember, or
easy to type. Luckily, Spack has its own interface for using modules.

^^^^^^^^^^^^^
Shell support
^^^^^^^^^^^^^

To enable additional Spack commands for loading and unloading module files,
and to add the correct path to ``MODULEPATH``,  you need to source the appropriate
setup file in the ``$SPACK_ROOT/share/spack`` directory. This will activate shell
support for the commands that need it. For ``bash``, ``ksh`` or ``zsh`` users:

.. code-block:: console

   $ . ${SPACK_ROOT}/share/spack/setup-env.sh

For ``csh`` and ``tcsh`` instead:

.. code-block:: console

   $ set SPACK_ROOT ...
   $ source $SPACK_ROOT/share/spack/setup-env.csh

Note that in the latter case it is necessary to explicitly set ``SPACK_ROOT``
before sourcing the setup file (you will get a meaningful error message
if you don't).

If you want to have Spack's shell support available on the command line at
any login you can put this source line in one of the files that are sourced
at startup (like ``.profile``, ``.bashrc`` or ``.cshrc``). Be aware though
that the startup time may be slightly increased because of that.


.. _cmd-spack-load:

^^^^^^^^^^^^^^^^^^^^^^^
``spack load / unload``
^^^^^^^^^^^^^^^^^^^^^^^

Once you have shell support enabled you can use the same spec syntax
you're used to and you can use the same shortened names you use
everywhere else in Spack.

For example this will add the ``mpich`` package built with ``gcc`` to your path:

.. code-block:: console

   $ spack install mpich %gcc@4.4.7

   # ... wait for install ...

   $ spack load mpich %gcc@4.4.7
   $ which mpicc
   ~/spack/opt/linux-debian7-x86_64/gcc@4.4.7/mpich@3.0.4/bin/mpicc

These commands will add appropriate directories to your ``PATH``,
``MANPATH``, ``CPATH``, and ``LD_LIBRARY_PATH``.  When you no longer
want to use a package, you can type unload or unuse similarly:

.. code-block:: console

   $ spack unload mpich %gcc@4.4.7

.. note::

   The ``load`` and ``unload`` subcommands are only available if you
   have enabled Spack's shell support. These command DO NOT use the
   underlying Spack-generated module files.

^^^^^^^^^^^^^^^
Ambiguous specs
^^^^^^^^^^^^^^^

If a spec used with load/unload or is ambiguous (i.e. more than one
installed package matches it), then Spack will warn you:

.. code-block:: console

   $ spack load libelf
   ==> Error: libelf matches multiple packages.
   Matching packages:
     libelf@0.8.13%gcc@4.4.7 arch=linux-debian7-x86_64
     libelf@0.8.13%intel@15.0.0 arch=linux-debian7-x86_64
   Use a more specific spec

You can either type the ``spack load`` command again with a fully
qualified argument, or you can add just enough extra constraints to
identify one package.  For example, above, the key differentiator is
that one ``libelf`` is built with the Intel compiler, while the other
used ``gcc``.  You could therefore just type:

.. code-block:: console

   $ spack load libelf %intel

To identify just the one built with the Intel compiler.

.. _cmd-spack-module-loads:

^^^^^^^^^^^^^^^^^^^^^^^^^^
``spack module tcl loads``
^^^^^^^^^^^^^^^^^^^^^^^^^^

In some cases, it is desirable to use a Spack-generated module, rather
than relying on Spack's built-in user-environment modification
capabilities. To translate a spec into a module name, use ``spack
module tcl loads`` or ``spack module lmod loads`` depending on the
module system desired.


To load not just a module, but also all the modules it depends on, use
the ``--dependencies`` option. This is not required for most modules
because Spack builds binaries with RPATH support.  However, not all
packages use RPATH to find their dependencies: this can be true in
particular for Python extensions, which are currently *not* built with
RPATH.

Scripts to load modules recursively may be made with the command:

.. code-block:: console

    $ spack module tcl loads --dependencies <spec>

An equivalent alternative using `process substitution <http://tldp.org/LDP/abs/html/process-sub.html>`_ is:

.. code-block :: console

    $ source <( spack module tcl loads --dependencies <spec> )


^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Module Commands for Shell Scripts
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Although Spack is flexible, the ``module`` command is much faster.
This could become an issue when emitting a series of ``spack load``
commands inside a shell script.  By adding the ``--dependencies`` flag,
``spack module tcl loads`` may also be used to generate code that can be
cut-and-pasted into a shell script.  For example:

.. code-block:: console

    $ spack module tcl loads --dependencies py-numpy git
    # bzip2@1.0.6%gcc@4.9.3=linux-x86_64
    module load bzip2-1.0.6-gcc-4.9.3-ktnrhkrmbbtlvnagfatrarzjojmkvzsx
    # ncurses@6.0%gcc@4.9.3=linux-x86_64
    module load ncurses-6.0-gcc-4.9.3-kaazyneh3bjkfnalunchyqtygoe2mncv
    # zlib@1.2.8%gcc@4.9.3=linux-x86_64
    module load zlib-1.2.8-gcc-4.9.3-v3ufwaahjnviyvgjcelo36nywx2ufj7z
    # sqlite@3.8.5%gcc@4.9.3=linux-x86_64
    module load sqlite-3.8.5-gcc-4.9.3-a3eediswgd5f3rmto7g3szoew5nhehbr
    # readline@6.3%gcc@4.9.3=linux-x86_64
    module load readline-6.3-gcc-4.9.3-se6r3lsycrwxyhreg4lqirp6xixxejh3
    # python@3.5.1%gcc@4.9.3=linux-x86_64
    module load python-3.5.1-gcc-4.9.3-5q5rsrtjld4u6jiicuvtnx52m7tfhegi
    # py-setuptools@20.5%gcc@4.9.3=linux-x86_64
    module load py-setuptools-20.5-gcc-4.9.3-4qr2suj6p6glepnedmwhl4f62x64wxw2
    # py-nose@1.3.7%gcc@4.9.3=linux-x86_64
    module load py-nose-1.3.7-gcc-4.9.3-pwhtjw2dvdvfzjwuuztkzr7b4l6zepli
    # openblas@0.2.17%gcc@4.9.3+shared=linux-x86_64
    module load openblas-0.2.17-gcc-4.9.3-pw6rmlom7apfsnjtzfttyayzc7nx5e7y
    # py-numpy@1.11.0%gcc@4.9.3+blas+lapack=linux-x86_64
    module load py-numpy-1.11.0-gcc-4.9.3-mulodttw5pcyjufva4htsktwty4qd52r
    # curl@7.47.1%gcc@4.9.3=linux-x86_64
    module load curl-7.47.1-gcc-4.9.3-ohz3fwsepm3b462p5lnaquv7op7naqbi
    # autoconf@2.69%gcc@4.9.3=linux-x86_64
    module load autoconf-2.69-gcc-4.9.3-bkibjqhgqm5e3o423ogfv2y3o6h2uoq4
    # cmake@3.5.0%gcc@4.9.3~doc+ncurses+openssl~qt=linux-x86_64
    module load cmake-3.5.0-gcc-4.9.3-x7xnsklmgwla3ubfgzppamtbqk5rwn7t
    # expat@2.1.0%gcc@4.9.3=linux-x86_64
    module load expat-2.1.0-gcc-4.9.3-6pkz2ucnk2e62imwakejjvbv6egncppd
    # git@2.8.0-rc2%gcc@4.9.3+curl+expat=linux-x86_64
    module load git-2.8.0-rc2-gcc-4.9.3-3bib4hqtnv5xjjoq5ugt3inblt4xrgkd

The script may be further edited by removing unnecessary modules.


^^^^^^^^^^^^^^^
Module Prefixes
^^^^^^^^^^^^^^^

On some systems, modules are automatically prefixed with a certain
string; ``spack module tcl loads`` needs to know about that prefix when it
issues ``module load`` commands.  Add the ``--prefix`` option to your
``spack module tcl loads`` commands if this is necessary.

For example, consider the following on one system:

.. code-block:: console

    $ module avail
    linux-SuSE11-x86_64/antlr-2.7.7-gcc-5.3.0-bdpl46y

    $ spack module tcl loads antlr    # WRONG!
    # antlr@2.7.7%gcc@5.3.0~csharp+cxx~java~python arch=linux-SuSE11-x86_64
    module load antlr-2.7.7-gcc-5.3.0-bdpl46y

    $ spack module tcl loads --prefix linux-SuSE11-x86_64/ antlr
    # antlr@2.7.7%gcc@5.3.0~csharp+cxx~java~python arch=linux-SuSE11-x86_64
    module load linux-SuSE11-x86_64/antlr-2.7.7-gcc-5.3.0-bdpl46y

-------------------------
Module file customization
-------------------------

Module files are generated by post-install hooks after the successful
installation of a package. The table below summarizes the essential
information associated with the different file formats
that can be generated by Spack:

  +-----------------------------+--------------------+-------------------------------+----------------------------------------------+----------------------+
  |                             | **Hook name**      |  **Default root directory**   | **Default template file**                    | **Compatible tools** |
  +=============================+====================+===============================+==============================================+======================+
  |  **TCL - Non-Hierarchical** | ``tcl``            |  share/spack/modules          | share/spack/templates/modules/modulefile.tcl | Env. Modules/LMod    |
  +-----------------------------+--------------------+-------------------------------+----------------------------------------------+----------------------+
  |  **Lua - Hierarchical**     | ``lmod``           |  share/spack/lmod             | share/spack/templates/modules/modulefile.lua | LMod                 |
  +-----------------------------+--------------------+-------------------------------+----------------------------------------------+----------------------+


Spack ships with sensible defaults for the generation of module files, but
you can customize many aspects of it to accommodate package or site specific needs.
In general you can override or extend the default behavior by:

 1. overriding certain callback APIs in the Python packages
 2. writing specific rules in the ``modules.yaml`` configuration file
 3. writing your own templates to override or extend the defaults

The former method let you express changes in the run-time environment
that are needed to use the installed software properly, e.g. injecting variables
from language interpreters into their extensions. The latter two instead permit to
fine tune the filesystem layout, content and creation of module files to meet
site specific conventions.

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Override API calls in ``package.py``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There are two methods that you can override in any ``package.py`` to affect the
content of the module files generated by Spack. The first one:

.. code-block:: python

   def setup_run_environment(self, env):
       pass

can alter the content of the module file associated with the same package where it is overridden.
The second method:

.. code-block:: python

   def setup_dependent_run_environment(self, env, dependent_spec):
       pass

can instead inject run-time environment modifications in the module files of packages
that depend on it. In both cases you need to fill ``run_env`` with the desired
list of environment modifications.

.. admonition:: The ``r`` package and callback APIs

  An example in which it is crucial to override both methods
  is given by the ``r`` package. This package installs libraries and headers
  in non-standard locations and it is possible to prepend the appropriate directory
  to the corresponding environment variables:

  ================== =================================
   LIBRARY_PATH       ``self.prefix/rlib/R/lib``
   LD_LIBRARY_PATH    ``self.prefix/rlib/R/lib``
   CPATH              ``self.prefix/rlib/R/include``
  ================== =================================

  with the following snippet:

  .. literalinclude:: _spack_root/var/spack/repos/builtin/packages/r/package.py
     :pyobject: R.setup_run_environment

  The ``r`` package also knows which environment variable should be modified
  to make language extensions provided by other packages available, and modifies
  it appropriately in the override of the second method:

  .. literalinclude:: _spack_root/var/spack/repos/builtin/packages/r/package.py
     :pyobject: R.setup_dependent_run_environment

.. _modules-yaml:

^^^^^^^^^^^^^^^^^^^^^^^^^^
Write a configuration file
^^^^^^^^^^^^^^^^^^^^^^^^^^

The configuration files that control module generation behavior
are named ``modules.yaml``. The default configuration:

.. literalinclude:: _spack_root/etc/spack/defaults/modules.yaml
   :language: yaml

activates the hooks to generate ``tcl`` module files and inspects
the installation folder of each package for the presence of a set of subdirectories
(``bin``, ``man``, ``share/man``, etc.). If any is found its full path is prepended
to the environment variables listed below the folder name.

""""""""""""""""""""
Activate other hooks
""""""""""""""""""""

Any other module file generator shipped with Spack can be activated adding it to the
list under the ``enable`` key in the module file. Currently the only generator that
is not active by default is ``lmod``, which produces hierarchical lua module files.

Each module system can then be configured separately. In fact, you should list configuration
options that affect a particular type of module files under a top level key corresponding
to the generator being customized:

.. code-block:: yaml

   modules:
     enable:
       - tcl
       - lmod
     tcl:
       # contains environment modules specific customizations
     lmod:
       # contains lmod specific customizations

In general, the configuration options that you can use in ``modules.yaml`` will
either change the layout of the module files on the filesystem, or they will affect
their content. For the latter point it is possible to use anonymous specs
to fine tune the set of packages on which the modifications should be applied.

.. _anonymous_specs:

""""""""""""""""""""""""""""
Selection by anonymous specs
""""""""""""""""""""""""""""

In the configuration file you can use *anonymous specs* (i.e. specs
that **are not required to have a root package** and are thus used just
to express constraints) to apply certain modifications on a selected set
of the installed software. For instance, in the snippet below:

.. code-block:: yaml

   modules:
     tcl:
       # The keyword `all` selects every package
       all:
         environment:
           set:
             BAR: 'bar'
       # This anonymous spec selects any package that
       # depends on openmpi. The double colon at the
       # end clears the set of rules that matched so far.
       ^openmpi::
         environment:
           set:
             BAR: 'baz'
       # Selects any zlib package
       zlib:
         environment:
           prepend_path:
             LD_LIBRARY_PATH: 'foo'
       # Selects zlib compiled with gcc@4.8
       zlib%gcc@4.8:
         environment:
           unset:
           - FOOBAR

you are instructing Spack to set the environment variable ``BAR=bar`` for every module,
unless the associated spec satisfies ``^openmpi`` in which case ``BAR=baz``.
In addition in any spec that satisfies ``zlib`` the value ``foo`` will be
prepended to ``LD_LIBRARY_PATH`` and in any spec that satisfies ``zlib%gcc@4.8``
the variable ``FOOBAR`` will be unset.

.. note::
   Order does matter
     The modifications associated with the ``all`` keyword are always evaluated
     first, no matter where they appear in the configuration file. All the other
     spec constraints are instead evaluated top to bottom.

""""""""""""""""""""""""""""""""""""""""""""
Blacklist or whitelist specific module files
""""""""""""""""""""""""""""""""""""""""""""

You can use anonymous specs also to prevent module files from being written or
to force them to be written. Consider the case where you want to hide from users
all the boilerplate software that you had to build in order to bootstrap a new
compiler. Suppose for instance that ``gcc@4.4.7`` is the compiler provided by
your system. If you write a configuration file like:

.. code-block:: yaml

   modules:
     tcl:
       whitelist: ['gcc', 'llvm']  # Whitelist will have precedence over blacklist
       blacklist: ['%gcc@4.4.7']   # Assuming gcc@4.4.7 is the system compiler

you will prevent the generation of module files for any package that
is compiled with ``gcc@4.4.7``, with the only exception of any ``gcc``
or any ``llvm`` installation.


.. _modules-projections:

"""""""""""""""""""""""""""""""
Customize the naming of modules
"""""""""""""""""""""""""""""""

The names of environment modules generated by spack are not always easy to
fully comprehend due to the long hash in the name. There are three module
configuration options to help with that. The first is a global setting to
adjust the hash length. It can be set anywhere from 0 to 32 and has a default
length of 7. This is the representation of the hash in the module file name and
does not affect the size of the package hash. Be aware that the smaller the
hash length the more likely naming conflicts will occur. The following snippet
shows how to set hash length in the module file names:

.. code-block:: yaml

   modules:
     tcl:
       hash_length: 7

To help make module names more readable, and to help alleviate name conflicts
with a short hash, one can use the ``suffixes`` option in the modules
configuration file. This option will add strings to modules that match a spec.
For instance, the following config options,

.. code-block:: yaml

   modules:
     tcl:
       all:
         suffixes:
           ^python@2.7.12: 'python-2.7.12'
           ^openblas: 'openblas'

will add a ``python-2.7.12`` version string to any packages compiled with
python matching the spec, ``python@2.7.12``. This is useful to know which
version of python a set of python extensions is associated with. Likewise, the
``openblas`` string is attached to any program that has openblas in the spec,
most likely via the ``+blas`` variant specification.

The most heavyweight solution to module naming is to change the entire
naming convention for module files. This uses the projections format
covered in :ref:`adding_projections_to_views`.

.. code-block:: yaml

  modules:
    tcl:
      projections:
        all: '{name}/{version}-{compiler.name}-{compiler.version}-module'
        ^mpi: '{name}/{version}-{^mpi.name}-{^mpi.version}-{compiler.name}-{compiler.version}-module'

will create module files that are nested in directories by package
name, contain the version and compiler name and version, and have the
word ``module`` before the hash for all specs that do not depend on
mpi, and will have the same information plus the MPI implementation
name and version for all packages that depend on mpi.

When specifying module names by projection for Lmod modules, we
recommend NOT including names of dependencies (e.g., MPI, compilers)
that are already in the LMod hierarchy.



.. note::
   TCL modules
     TCL modules also allow for explicit conflicts between modulefiles.

     .. code-block:: yaml

        modules:
          enable:
            - tcl
          tcl:
            projections:
              all: '{name}/{version}-{compiler.name}-{compiler.version}'
            all:
              conflict:
                - '{name}'
                - 'intel/14.0.1'

     will create module files that will conflict with ``intel/14.0.1`` and with the
     base directory of the same module, effectively preventing the possibility to
     load two or more versions of the same software at the same time. The tokens
     that are available for use in this directive are the same understood by
     the :meth:`~spack.spec.Spec.format` method.


.. note::
   LMod hierarchical module files
     When ``lmod`` is activated Spack will generate a set of hierarchical lua module
     files that are understood by LMod. The hierarchy will always contain the
     two layers ``Core`` / ``Compiler`` but can be further extended to
     any of the virtual dependencies present in Spack. A case that could be useful in
     practice is for instance:

     .. code-block:: yaml

       modules:
         enable:
           - lmod
         lmod:
           core_compilers:
             - 'gcc@4.8'
           core_specs:
             - 'python'
           hierarchy:
             - 'mpi'
             - 'lapack'

     that will generate a hierarchy in which the ``lapack`` and ``mpi`` layer can be switched
     independently. This allows a site to build the same libraries or applications against different
     implementations of ``mpi`` and ``lapack``, and let LMod switch safely from one to the
     other.

     All packages built with a compiler in ``core_compilers`` and all
     packages that satisfy a spec in ``core_specs`` will be put in the
     ``Core`` hierarchy of the lua modules.

.. warning::
  Consistency of Core packages
   The user is responsible for maintining consistency among core packages, as ``core_specs``
   bypasses the hierarchy that allows LMod to safely switch between coherent software stacks.

.. warning::
  Deep hierarchies and ``lmod spider``
   For hierarchies that are deeper than three layers ``lmod spider`` may have some issues.
   See `this discussion on the LMod project <https://github.com/TACC/Lmod/issues/114>`_.

""""""""""""""""""""""""""""""""""""
Filter out environment modifications
""""""""""""""""""""""""""""""""""""

Modifications to certain environment variables in module files are there by
default, for instance because they are generated by prefix inspections.
If you want to prevent modifications to some environment variables, you can
do so by using the environment blacklist:

.. code-block:: yaml

   modules:
     tcl:
       all:
         filter:
           # Exclude changes to any of these variables
           environment_blacklist: ['CPATH', 'LIBRARY_PATH']

The configuration above will generate module files that will not contain
modifications to either ``CPATH`` or ``LIBRARY_PATH``.


.. _autoloading-dependencies:

"""""""""""""""""""""
Autoload dependencies
"""""""""""""""""""""

In some cases it can be useful to have module files that automatically load
their dependencies.  This may be the case for Python extensions, if not
activated using ``spack activate``:

.. code-block:: yaml

   modules:
     tcl:
       ^python:
         autoload: 'direct'

The configuration file above will produce module files that will
load their direct dependencies if the package installed depends on ``python``.
The allowed values for the ``autoload`` statement are either ``none``,
``direct`` or ``all``.  The default is ``none``.

.. tip::
  Building external software
     Setting ``autoload`` to ``direct`` for all packages can be useful
     when building software outside of a Spack installation that depends on
     artifacts in that installation.  E.g. (adjust ``lmod`` vs ``tcl``
     as appropriate):

  .. code-block:: yaml

     modules:
       lmod:
         all:
           autoload: 'direct'

.. note::
  TCL prerequisites
     In the ``tcl`` section of the configuration file it is possible to use
     the ``prerequisites`` directive that accepts the same values as
     ``autoload``. It will produce module files that have a ``prereq``
     statement instead of automatically loading other modules.

------------------------
Maintaining Module Files
------------------------

Each type of module file has a command with the same name associated
with it. The actions these commands permit are usually associated
with the maintenance of a production environment. Here's, for instance,
a sample of the features of the ``spack module tcl`` command:

.. command-output:: spack module tcl --help

.. _cmd-spack-module-refresh:

^^^^^^^^^^^^^^^^^^^^^^^^^^
Refresh the set of modules
^^^^^^^^^^^^^^^^^^^^^^^^^^

The subcommand that regenerates module files to update their content or
their layout is ``refresh``:

.. command-output:: spack module tcl refresh --help

A set of packages can be selected using anonymous specs for the optional
``constraint`` positional argument. Optionally the entire tree can be deleted
before regeneration if the change in layout is radical.

.. _cmd-spack-module-rm:

^^^^^^^^^^^^^^^^^^^
Delete module files
^^^^^^^^^^^^^^^^^^^

If instead what you need is just to delete a few module files, then the right
subcommand is ``rm``:

.. command-output:: spack module tcl rm --help

.. note::
  We care about your module files!
   Every modification done on modules
   that are already existing will ask for a confirmation by default. If
   the command is used in a script it is possible though to pass the
   ``-y`` argument, that will skip this safety measure.
