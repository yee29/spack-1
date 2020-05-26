# Copyright 2013-2020 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack import *


class Adios2(CMakePackage):
    """The Adaptable Input Output System version 2,
    developed in the Exascale Computing Program"""

    homepage = "https://csmd.ornl.gov/software/adios2"
    url = "https://github.com/ornladios/ADIOS2/archive/v2.5.0.tar.gz"
    git = "https://github.com/ornladios/ADIOS2.git"

    maintainers = ['ax3l', 'chuckatkins', 'williamfgc']

    version('master', branch='master')
    version('2.5.0', sha256='7c8ff3bf5441dd662806df9650c56a669359cb0185ea232ecb3578de7b065329')
    version('2.4.0', sha256='50ecea04b1e41c88835b4b3fd4e7bf0a0a2a3129855c9cc4ba6cf6a1575106e2')
    version('2.3.1', sha256='3bf81ccc20a7f2715935349336a76ba4c8402355e1dc3848fcd6f4c3c5931893')

    # general build options
    variant('mpi', default=True, description='Enable MPI')
    variant('build_type', default='Release',
            description='CMake build type',
            values=('Debug', 'Release', 'RelWithDebInfo', 'MinSizeRel'))
    variant('shared', default=True,
            description='Also build shared libraries')
    variant('pic', default=True,
            description='Enable position independent code '
                        '(for usage of static in shared downstream deps)')
    variant('endian_reverse', default=False,
            description='Enable endian conversion if a different '
                        'endianness is detected between write and read.')

    # compression libraries
    variant('blosc', default=True,
            description='Enable Blosc compression')
    variant('bzip2', default=True,
            description='Enable BZip2 compression')
    variant('zfp', default=True,
            description='Enable ZFP compression')
    variant('png', default=True,
            description='Enable PNG compression')
    variant('sz', default=True,
            description='Enable SZ compression')

    # transport engines
    variant('sst', default=True,
            description='Enable the SST staging engine')
    variant('dataman', default=True,
            description='Enable the DataMan engine for WAN transports')
    variant('dataspaces', default=False,
            description='Enable support for DATASPACES')
    variant('ssc', default=True,
            description='Enable the SSC staging engine')
    variant('hdf5', default=False,
            description='Enable the HDF5 engine')

    # optional language bindings, C++11 and C always provided
    variant('python', default=False,
            description='Enable the Python bindings')
    variant('fortran', default=True,
            description='Enable the Fortran bindings')

    # requires mature C++11 implementations
    conflicts('%gcc@:4.7')
    conflicts('%intel@:15')
    conflicts('%pgi@:14')

    # shared libs must have position-independent code
    conflicts('+shared ~pic')

    # DataMan needs dlopen
    conflicts('+dataman', when='~shared')

    depends_on('cmake@3.6.0:', type='build')
    depends_on('pkgconfig', type='build')

    depends_on('libffi', when='+sst')            # optional in DILL
    depends_on('libfabric@1.6.0:', when='+sst')  # optional in EVPath and SST
    # depends_on('bison', when='+sst')     # optional in FFS, broken package
    # depends_on('flex', when='+sst')      # optional in FFS, depends on BISON

    depends_on('mpi', when='+mpi')
    depends_on('libzmq', when='+dataman')
    depends_on('libzmq', when='@2.4: +ssc')
    depends_on('dataspaces@1.8.0:', when='+dataspaces')

    depends_on('hdf5', when='+hdf5')
    depends_on('hdf5+mpi', when='+hdf5+mpi')

    depends_on('c-blosc', when='@2.4: +blosc')
    depends_on('bzip2', when='@2.4: +bzip2')
    depends_on('libpng@1.6:', when='@2.4: +png')
    depends_on('zfp@0.5.1:', when='+zfp')
    depends_on('sz@:2.0.2.0', when='+sz')

    extends('python', when='+python')
    depends_on('python@2.7:2.8,3.5:',
               when='@:2.4.0 +python',
               type=('build', 'run'))
    depends_on('python@3.5:', when='@2.5.0: +python',
               type=('build', 'run'))
    depends_on('python@2.7:2.8,3.5:', when='@:2.4.0', type='test')
    depends_on('python@3.5:', when='@2.5.0:', type='test')
    depends_on('py-numpy@1.6.1:', type=('build', 'run'), when='+python')
    depends_on('py-mpi4py@2.0.0:', type=('build', 'run'), when='+mpi +python')

    # Fix findmpi when called by dependees
    # See https://github.com/ornladios/ADIOS2/pull/1632
    patch('cmake-update-findmpi.patch', when='@2.4.0')

    # Fix the signature of the builtin clear_cache function in the
    # third-party dill library.
    # See https://github.com/ornladios/ADIOS2/pull/1899
    patch('2.5-fix-clear_cache.patch', when='@2.5.0')

    def setup_build_environment(self, env):
        # https://github.com/ornladios/ADIOS2/issues/2228
        if self.spec.satisfies('%gcc@10: +fortran'):
            env.set('FFLAGS', '-fallow-argument-mismatch')

    def cmake_args(self):
        spec = self.spec

        args = [
            '-DBUILD_SHARED_LIBS:BOOL={0}'.format(
                'ON' if '+shared' in spec else 'OFF'),
            '-DADIOS2_BUILD_TESTING=OFF',
            '-DADIOS2_BUILD_EXAMPLES=OFF',
            '-DADIOS2_USE_MPI={0}'.format(
                'ON' if '+mpi' in spec else 'OFF'),
            '-DADIOS2_USE_MGARD=OFF',
            '-DADIOS2_USE_ZFP={0}'.format(
                'ON' if '+zfp' in spec else 'OFF'),
            '-DADIOS2_USE_SZ={0}'.format(
                'ON' if '+sz' in spec else 'OFF'),
            '-DADIOS2_USE_DataMan={0}'.format(
                'ON' if '+dataman' in spec else 'OFF'),
            '-DADIOS2_USE_SST={0}'.format(
                'ON' if '+sst' in spec else 'OFF'),
            '-DADIOS2_USE_HDF5={0}'.format(
                'ON' if '+hdf5' in spec else 'OFF'),
            '-DADIOS2_USE_Python={0}'.format(
                'ON' if '+python' in spec else 'OFF'),
            '-DADIOS2_USE_Fortran={0}'.format(
                'ON' if '+fortran' in spec else 'OFF'),
            '-DADIOS2_USE_Endian_Reverse={0}'.format(
                'ON' if '+endian_reverse' in spec else 'OFF'),
            '-DBUILD_TESTING:BOOL={0}'.format(
                'ON' if self.run_tests else 'OFF'),
        ]

        if spec.version >= Version('2.4.0'):
            args.append('-DADIOS2_USE_Blosc={0}'.format(
                'ON' if '+blosc' in spec else 'OFF'))
            args.append('-DADIOS2_USE_BZip2={0}'.format(
                'ON' if '+bzip2' in spec else 'OFF'))
            args.append('-DADIOS2_USE_PNG={0}'.format(
                'ON' if '+png' in spec else 'OFF'))
            args.append('-DADIOS2_USE_SSC={0}'.format(
                'ON' if '+ssc' in spec else 'OFF'))

        if spec.version >= Version('2.5.0'):
            args.append('-DADIOS2_USE_DataSpaces={0}'.format(
                'ON' if '+dataspaces' in spec else 'OFF'))

        if '+sst' in spec:
            args.extend([
                # Broken dependency package
                '-DCMAKE_DISABLE_FIND_PACKAGE_BISON=TRUE',
                # Depends on ^
                '-DCMAKE_DISABLE_FIND_PACKAGE_FLEX=TRUE',

                # Not yet packaged
                '-DCMAKE_DISABLE_FIND_PACKAGE_CrayDRC=TRUE',
                '-DCMAKE_DISABLE_FIND_PACKAGE_NVSTREAM=TRUE'
            ])

        if spec.satisfies('~shared'):
            args.append('-DCMAKE_POSITION_INDEPENDENT_CODE:BOOL={0}'.format(
                'ON' if '+pic' in spec else 'OFF'))

        if spec.satisfies('+python') or self.run_tests:
            args.append('-DPYTHON_EXECUTABLE:FILEPATH=%s'
                        % spec['python'].command.path)

        return args
