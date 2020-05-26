# Copyright 2013-2020 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack import *


class SuperluDist(CMakePackage):
    """A general purpose library for the direct solution of large, sparse,
    nonsymmetric systems of linear equations on high performance machines."""

    homepage = "http://crd-legacy.lbl.gov/~xiaoye/SuperLU/"
    url      = "https://github.com/xiaoyeli/superlu_dist/archive/v6.0.0.tar.gz"
    git      = "https://github.com/xiaoyeli/superlu_dist.git"

    maintainers = ['xiaoye', 'gchavez2', 'balay']

    version('develop', branch='master')
    version('xsdk-0.2.0', tag='xsdk-0.2.0')
    version('6.3.1', sha256='3787c2755acd6aadbb4d9029138c293a7570a2ed228806676edcc7e1d3f5a1d3')
    version('6.3.0', sha256='daf3264706caccae2b8fd5a572e40275f1e128fa235cb7c21ee2f8051c11af95')
    version('6.2.0', sha256='15ad1badd81b41e37941dd124d06d3b92e51c4f0ff532ad23fb09c4ebfe6eb9e')
    version('6.1.1', sha256='35d25cff592c724439870444ed45e1d1d15ca2c65f02ccd4b83a6d3c9d220bd1')
    version('6.1.0', sha256='92c6d1424dd830ee2d1e7396a418a5f6645160aea8472e558c4e4bfe006593c4')
    version('6.0.0', sha256='ff6cdfa0263d595708bbb6d11fb780915d8cfddab438db651e246ea292f37ee4')
    version('5.4.0', sha256='3ac238fe082106a2c4dbaf0c22af1ff1247308ffa8f053de9d78c3ec7dd0d801')
    version('5.3.0', sha256='49ed110bdef1e284a0181d6c7dd1fae3aa110cb45f67c6aa5cb791070304d670')
    version('5.2.2', sha256='65cfb9ace9a81f7affac4ad92b9571badf0f10155b3468531b0fffde3bd8e727')
    version('5.2.1', sha256='67cf3c46cbded4cee68e2a9d601c30ab13b08091c8cdad95b0a8e018b6d5d1f1')
    version('5.1.3', sha256='58e3dfdb4ae6f8e3f6f3d5ee5e851af59b967c4483cdb3b15ccd1dbdf38f44f9')
    version('5.1.2', sha256='e34865ad6696ee6a6d178b4a01c8e19103a7d241ba9de043603970d63b0ee1e2')
    version('5.1.0', sha256='73f292ab748b590b6dd7469e6986aeb95d279b8b8b3da511c695a396bdbc996c')
    version('5.0.0', sha256='78d1d6460ff16b3f71e4bcd7306397574d54d421249553ccc26567f00a10bfc6')

    variant('int64', default=False, description='Build with 64 bit integers')
    variant('openmp', default=False, description='Build with OpenMP support (needs a good multithreaded BLAS implementation for good performance)')
    variant('shared', default=True, description='Build shared libraries')

    depends_on('mpi')
    depends_on('blas')
    depends_on('lapack')
    depends_on('parmetis')
    depends_on('metis@5:')

    patch('xl-611.patch', when='@:6.1.1 %xl')
    patch('xl-611.patch', when='@:6.1.1 %xl_r')

    def cmake_args(self):
        spec = self.spec
        args = [
            '-DCMAKE_C_COMPILER=%s' % spec['mpi'].mpicc,
            '-DCMAKE_CXX_COMPILER=%s' % spec['mpi'].mpicxx,
            '-DCMAKE_INSTALL_LIBDIR:STRING=%s' % self.prefix.lib,
            '-DTPL_BLAS_LIBRARIES=%s' % spec['blas'].libs.joined(";"),
            '-DTPL_LAPACK_LIBRARIES=%s' % spec['lapack'].libs.joined(";"),
            '-DUSE_XSDK_DEFAULTS=YES',
            '-DTPL_PARMETIS_LIBRARIES=%s' % spec['parmetis'].libs.ld_flags +
            ';' + spec['metis'].libs.ld_flags,
            '-DTPL_PARMETIS_INCLUDE_DIRS=%s' %
            spec['parmetis'].prefix.include +
            ';' + spec['metis'].prefix.include
        ]

        if (spec.satisfies('%xl') or spec.satisfies('%xl_r')) and \
           spec.satisfies('@:6.1.1'):
            args.append('-DCMAKE_C_FLAGS=-DNoChange')

        if '+int64' in spec:
            args.append('-DXSDK_INDEX_SIZE=64')
        else:
            args.append('-DXSDK_INDEX_SIZE=32')

        if '+openmp' in spec:
            args.append('-Denable_openmp=ON')
        else:
            args.append('-Denable_openmp=OFF')
            args.append('-DCMAKE_DISABLE_FIND_PACKAGE_OpenMP=ON')

        if '+shared' in spec:
            args.append('-DBUILD_SHARED_LIBS:BOOL=ON')
        else:
            args.append('-DBUILD_SHARED_LIBS:BOOL=OFF')
        return args

    def flag_handler(self, name, flags):
        flags = list(flags)
        if name == 'cxxflags':
            flags.append(self.compiler.cxx11_flag)
        if name == 'cflags' and '%pgi' not in self.spec:
            flags.append('-std=c99')
        return (None, None, flags)
