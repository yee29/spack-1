# Copyright 2013-2020 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import collections
import os.path
import platform
import shutil

import llnl.util.filesystem
import pytest
import spack.architecture
import spack.concretize
import spack.paths
import spack.relocate
import spack.spec
import spack.store
import spack.tengine
import spack.util.executable


@pytest.fixture(params=[True, False])
def is_relocatable(request):
    return request.param


@pytest.fixture()
def source_file(tmpdir, is_relocatable):
    """Returns the path to a source file of a relocatable executable."""
    if is_relocatable:
        template_src = os.path.join(
            spack.paths.test_path, 'data', 'templates', 'relocatable.c'
        )
        src = tmpdir.join('relocatable.c')
        shutil.copy(template_src, str(src))
    else:
        template_dirs = [
            os.path.join(spack.paths.test_path, 'data', 'templates')
        ]
        env = spack.tengine.make_environment(template_dirs)
        template = env.get_template('non_relocatable.c')
        text = template.render({'prefix': spack.store.layout.root})

        src = tmpdir.join('non_relocatable.c')
        src.write(text)

    return src


@pytest.fixture(params=['which_found', 'installed', 'to_be_installed'])
def expected_patchelf_path(request, mutable_database, monkeypatch):
    """Prepare the stage to tests different cases that can occur
    when searching for patchelf.
    """
    case = request.param

    # Mock the which function
    which_fn = {
        'which_found': lambda x: collections.namedtuple(
            '_', ['path']
        )('/usr/bin/patchelf')
    }
    monkeypatch.setattr(
        spack.util.executable, 'which',
        which_fn.setdefault(case, lambda x: None)
    )
    if case == 'which_found':
        return '/usr/bin/patchelf'

    # TODO: Mock a case for Darwin architecture

    spec = spack.spec.Spec('patchelf')
    spec.concretize()

    patchelf_cls = type(spec.package)
    do_install = patchelf_cls.do_install
    expected_path = os.path.join(spec.prefix.bin, 'patchelf')

    def do_install_mock(self, **kwargs):
        do_install(self, fake=True)
        with open(expected_path):
            pass

    monkeypatch.setattr(patchelf_cls, 'do_install', do_install_mock)
    if case == 'installed':
        spec.package.do_install()

    return expected_path


@pytest.fixture()
def mock_patchelf(tmpdir):
    import jinja2

    def _factory(output):
        f = tmpdir.mkdir('bin').join('patchelf')
        t = jinja2.Template('#!/bin/bash\n{{ output }}\n')
        f.write(t.render(output=output))
        f.chmod(0o755)
        return str(f)

    return _factory


@pytest.fixture()
def hello_world(tmpdir):
    source = tmpdir.join('main.c')
    source.write("""
#include <stdio.h>
int main(){
    printf("Hello world!");
}
""")

    def _factory(rpaths):
        gcc = spack.util.executable.which('gcc')
        executable = source.dirpath('main.x')
        rpath_str = ':'.join(rpaths)
        opts = [
            '-Wl,--disable-new-dtags',
            '-Wl,-rpath={0}'.format(rpath_str),
            str(source), '-o', str(executable)
        ]
        gcc(*opts)
        return executable

    return _factory


@pytest.mark.requires_executables(
    '/usr/bin/gcc', 'patchelf', 'strings', 'file'
)
def test_file_is_relocatable(source_file, is_relocatable):
    compiler = spack.util.executable.Executable('/usr/bin/gcc')
    executable = str(source_file).replace('.c', '.x')
    compiler_env = {
        'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    }
    compiler(str(source_file), '-o', executable, env=compiler_env)

    assert spack.relocate.is_binary(executable)
    assert spack.relocate.file_is_relocatable(executable) is is_relocatable


@pytest.mark.requires_executables('patchelf', 'strings', 'file')
def test_patchelf_is_relocatable():
    patchelf = spack.relocate._patchelf()
    assert llnl.util.filesystem.is_exe(patchelf)
    assert spack.relocate.file_is_relocatable(patchelf)


@pytest.mark.skipif(
    platform.system().lower() != 'linux',
    reason='implementation for MacOS still missing'
)
def test_file_is_relocatable_errors(tmpdir):
    # The file passed in as argument must exist...
    with pytest.raises(ValueError) as exc_info:
        spack.relocate.file_is_relocatable('/usr/bin/does_not_exist')
    assert 'does not exist' in str(exc_info.value)

    # ...and the argument must be an absolute path to it
    file = tmpdir.join('delete.me')
    file.write('foo')

    with llnl.util.filesystem.working_dir(str(tmpdir)):
        with pytest.raises(ValueError) as exc_info:
            spack.relocate.file_is_relocatable('delete.me')
        assert 'is not an absolute path' in str(exc_info.value)


@pytest.mark.skipif(
    platform.system().lower() != 'linux',
    reason='implementation for MacOS still missing'
)
def test_search_patchelf(expected_patchelf_path):
    current = spack.relocate._patchelf()
    assert current == expected_patchelf_path


@pytest.mark.parametrize('patchelf_behavior,expected', [
    ('echo ', []),
    ('echo /opt/foo/lib:/opt/foo/lib64', ['/opt/foo/lib', '/opt/foo/lib64']),
    ('exit 1', [])
])
def test_existing_rpaths(patchelf_behavior, expected, mock_patchelf):
    # Here we are mocking an executable that is always called "patchelf"
    # because that will skip the part where we try to build patchelf
    # by ourselves. The executable will output some rpaths like
    # `patchelf --print-rpath` would.
    path = mock_patchelf(patchelf_behavior)
    rpaths = spack.relocate._elf_rpaths_for(path)
    assert rpaths == expected


@pytest.mark.parametrize('start_path,path_root,paths,expected', [
    ('/usr/bin/test', '/usr', ['/usr/lib', '/usr/lib64', '/opt/local/lib'],
     ['$ORIGIN/../lib', '$ORIGIN/../lib64', '/opt/local/lib'])
])
def test_make_relative_paths(start_path, path_root, paths, expected):
    relatives = spack.relocate._make_relative(start_path, path_root, paths)
    assert relatives == expected


@pytest.mark.parametrize('start_path,relative_paths,expected', [
    # $ORIGIN will be replaced with os.path.dirname('usr/bin/test')
    # and then normalized
    ('/usr/bin/test',
     ['$ORIGIN/../lib', '$ORIGIN/../lib64', '/opt/local/lib'],
     ['/usr/lib', '/usr/lib64', '/opt/local/lib']),
    # Relative path without $ORIGIN
    ('/usr/bin/test', ['../local/lib'], ['../local/lib']),
])
def test_normalize_relative_paths(start_path, relative_paths, expected):
    normalized = spack.relocate._normalize_relative_paths(
        start_path, relative_paths
    )
    assert normalized == expected


def test_set_elf_rpaths(mock_patchelf):
    # Try to relocate a mock version of patchelf and check
    # the call made to patchelf itself
    patchelf = mock_patchelf('echo $@')
    rpaths = ['/usr/lib', '/usr/lib64', '/opt/local/lib']
    output = spack.relocate._set_elf_rpaths(patchelf, rpaths)

    # Assert that the arguments of the call to patchelf are as expected
    assert '--force-rpath' in output
    assert '--set-rpath ' + ':'.join(rpaths) in output
    assert patchelf in output


def test_set_elf_rpaths_warning(mock_patchelf):
    # Mock a failing patchelf command and ensure it warns users
    patchelf = mock_patchelf('exit 1')
    rpaths = ['/usr/lib', '/usr/lib64', '/opt/local/lib']
    # To avoid using capfd in order to check if the warning was triggered
    # here we just check that output is not set
    output = spack.relocate._set_elf_rpaths(patchelf, rpaths)
    assert output is None


@pytest.mark.requires_executables('patchelf', 'strings', 'file', 'gcc')
def test_replace_prefix_bin(hello_world):
    # Compile an "Hello world!" executable and set RPATHs
    executable = hello_world(rpaths=['/usr/lib', '/usr/lib64'])

    # Relocate the RPATHs
    spack.relocate._replace_prefix_bin(str(executable), '/usr', '/foo')

    # Check that the RPATHs changed
    patchelf = spack.util.executable.which('patchelf')
    output = patchelf('--print-rpath', str(executable), output=str)

    # Some compilers add rpaths so ensure changes included in final result
    assert '/foo/lib:/foo/lib64' in output


@pytest.mark.requires_executables('patchelf', 'strings', 'file', 'gcc')
def test_relocate_elf_binaries_absolute_paths(hello_world, tmpdir):
    # Create an executable, set some RPATHs, copy it to another location
    orig_binary = hello_world(rpaths=[str(tmpdir.mkdir('lib')), '/usr/lib64'])
    new_root = tmpdir.mkdir('another_dir')
    shutil.copy(str(orig_binary), str(new_root))

    # Relocate the binary
    new_binary = new_root.join('main.x')
    spack.relocate.relocate_elf_binaries(
        binaries=[str(new_binary)],
        orig_root=str(orig_binary.dirpath()),
        new_root=None,  # Not needed when relocating absolute paths
        new_prefixes={
            str(tmpdir): '/foo'
        },
        rel=False,
        # Not needed when relocating absolute paths
        orig_prefix=None, new_prefix=None
    )

    # Check that the RPATHs changed
    patchelf = spack.util.executable.which('patchelf')
    output = patchelf('--print-rpath', str(new_binary), output=str)

    # Some compilers add rpaths so ensure changes included in final result
    assert '/foo/lib:/usr/lib64' in output


@pytest.mark.requires_executables('patchelf', 'strings', 'file', 'gcc')
def test_relocate_elf_binaries_relative_paths(hello_world, tmpdir):
    # Create an executable, set some RPATHs, copy it to another location
    orig_binary = hello_world(
        rpaths=['$ORIGIN/lib', '$ORIGIN/lib64', '/opt/local/lib']
    )
    new_root = tmpdir.mkdir('another_dir')
    shutil.copy(str(orig_binary), str(new_root))

    # Relocate the binary
    new_binary = new_root.join('main.x')
    spack.relocate.relocate_elf_binaries(
        binaries=[str(new_binary)],
        orig_root=str(orig_binary.dirpath()),
        new_root=str(new_root),
        new_prefixes={str(tmpdir): '/foo'},
        rel=True,
        orig_prefix=str(orig_binary.dirpath()),
        new_prefix=str(new_root)
    )

    # Check that the RPATHs changed
    patchelf = spack.util.executable.which('patchelf')
    output = patchelf('--print-rpath', str(new_binary), output=str)

    # Some compilers add rpaths so ensure changes included in final result
    assert '/foo/lib:/foo/lib64:/opt/local/lib' in output
