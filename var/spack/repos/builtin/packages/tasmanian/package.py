# Copyright 2013-2020 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack import *


class Tasmanian(CMakePackage):
    """The Toolkit for Adaptive Stochastic Modeling and Non-Intrusive
    ApproximatioN is a robust library for high dimensional integration and
    interpolation as well as parameter calibration."""

    homepage = 'http://tasmanian.ornl.gov'
    url      = 'https://github.com/ORNL/TASMANIAN/archive/v7.1.tar.gz'
    git      = 'https://github.com/ORNL/TASMANIAN.git'

    maintainers = ['mkstoyanov']

    version('develop', branch='master')

    version('7.1', sha256='9c24a591506a478745b802f1fa5c557da7bc80b12d8070855de6bc7aaca7547a')
    version('7.0', sha256='4094ba4ee2f1831c575d00368c8471d3038f813398be2e500739cef5c7c4a47b')  # use for xsdk-0.5.0
    version('6.0', sha256='ceab842e9fbce2f2de971ba6226967caaf1627b3e5d10799c3bd2e7c3285ba8b')  # use for xsdk-0.4.0
    version('5.1', sha256='b0c1be505ce5f8041984c63edca9100d81df655733681858f5cc10e8c0c72711')

    version('5.0', sha256='2540bb63dea987ab205f7b375aff41f320b1de9bd7f1d1064ef96b22eeda1251',
            url='http://tasmanian.ornl.gov/documents/Tasmanian_v5.0.zip')

    variant('xsdkflags', default=False,
            description='enable XSDK defaults for Tasmanian')

    variant('openmp', default=True,
            description='add OpenMP support to Tasmanian')
    # tested with OpenMP 3.1 (clang4) through 4.0-4.5 (gcc 5 - 8)

    variant('blas', default=False,
            description='add BLAS support to Tasmanian')

    variant('mpi', default=False,
            description='add MPI support to Tasmanian')

    variant('cuda', default=False,
            description='add CUDA support to Tasmanian')

    variant('magma', default=False,
            description='add UTK MAGMA support to Tasmanian')

    variant('python', default=False,
            description='add Python binding for Tasmanian')

    variant('fortran', default=False,
            description='add Fortran 90/95 interface to Tasmanian')

    variant('build_type', default='Release',
            description='CMake build type',
            values=('Debug', 'Release'))

    depends_on('cmake@2.8:', type='build')
    depends_on('cmake@3.5:', type='build', when='@6.0:')
    depends_on('cmake@3.10:', type='build', when='@7.0:')

    depends_on('python@2.7:', when='+python', type=('build', 'run'))
    depends_on('py-numpy', when='+python', type=('build', 'run'))

    extends('python', when='+python', type=('build', 'run'))

    depends_on('mpi', when="+mpi", type=('build', 'run'))  # openmpi 2 and 3 tested

    depends_on('blas', when="+blas", type=('build', 'run'))  # openblas 0.2.18 or newer
    depends_on('lapack', when="+blas @7.1:", type=('build', 'run'))  # lapack used since 7.1

    depends_on('cuda@8.0.61:', when='+cuda', type=('build', 'run'))
    depends_on('cuda@8.0.61:', when='+magma', type=('build', 'run'))

    depends_on('magma@2.4.0:', when='+magma @6.0:', type=('build', 'run'))
    depends_on('magma@2.5.0:', when='+magma @7.0:', type=('build', 'run'))

    conflicts('-cuda', when='+magma')  # currently MAGMA only works with CUDA

    # old versions
    conflicts('+magma', when='@:5.1')  # magma does not work prior to 6.0
    conflicts('+mpi', when='@:5.1')    # MPI is broken prior to 6.0
    conflicts('+xsdkflags', when='@:5.1')  # 6.0 is the first version included in xSDK

    # patching some bugs
    patch('addons70.patch', when='@7.0')
    patch('packageconf70.patch', when='@7.0')

    def cmake_args(self):
        spec = self.spec

        if '+xsdkflags' in spec:
            args = [
                '-DUSE_XSDK_DEFAULTS:BOOL=ON',
                '-DXSDK_ENABLE_PYTHON:BOOL={0}'.format(
                    'ON' if '+python' in spec else 'OFF'),
                '-DTPL_ENABLE_MPI:BOOL={0}'.format(
                    'ON' if '+mpi' in spec else 'OFF'),
                '-DXSDK_ENABLE_OPENMP:BOOL={0}'.format(
                    'ON' if '+openmp' in spec else 'OFF'),
                '-DTPL_ENABLE_BLAS:BOOL={0}'.format(
                    'ON' if '+blas' in spec else 'OFF'),
                '-DXSDK_ENABLE_CUDA:BOOL={0}'.format(
                    'ON' if '+cuda' in spec else 'OFF'),
                '-DTPL_ENABLE_MAGMA:BOOL={0}'.format(
                    'ON' if '+magma' in spec else 'OFF'),
                '-DXSDK_ENABLE_FORTRAN:BOOL={0}'.format(
                    'ON' if '+fortran' in spec else 'OFF'), ]
        else:
            args = [
                '-DTasmanian_ENABLE_OPENMP:BOOL={0}'.format(
                    'ON' if '+openmp' in spec else 'OFF'),
                '-DTasmanian_ENABLE_BLAS:BOOL={0}'.format(
                    'ON' if '+blas' in spec else 'OFF'),
                '-DTasmanian_ENABLE_PYTHON:BOOL={0}'.format(
                    'ON' if '+python' in spec else 'OFF'),
                '-DTasmanian_ENABLE_MPI:BOOL={0}'.format(
                    'ON' if '+mpi' in spec else 'OFF'),
                '-DTasmanian_ENABLE_CUDA:BOOL={0}'.format(
                    'ON' if '+cuda' in spec else 'OFF'),
                '-DTasmanian_ENABLE_MAGMA:BOOL={0}'.format(
                    'ON' if '+magma' in spec else 'OFF'),
                '-DTasmanian_ENABLE_FORTRAN:BOOL={0}'.format(
                    'ON' if '+fortran' in spec else 'OFF'), ]

        if spec.satisfies('+python'):
            args.append('-DPYTHON_EXECUTABLE:FILEPATH={0}'.format(
                self.spec['python'].command.path))

        # _CUBLAS and _CUDA were separate options prior to 6.0
        # skipping _CUBLAS leads to peformance regression
        if spec.satisfies('@:5.1'):
            args.append('-DTasmanian_ENABLE_CUBLAS={0}'.format(
                        'ON' if '+cuda' in spec else 'OFF'))

        return args
