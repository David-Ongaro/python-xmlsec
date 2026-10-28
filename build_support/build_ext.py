import os
import sys
from distutils import log
from distutils.errors import DistutilsError

from setuptools.command.build_ext import build_ext as build_ext_orig

from .static_build import CrossCompileInfo, StaticBuildHelper


def _has_xmlsec_engine(include_dirs):
    """Return True if xmlSecKeyDataFormatEngine is declared in the xmlsec1 headers.

    The enum value was added in libxmlsec1 1.2.33 and is absent from builds
    compiled without OpenSSL ENGINE support (e.g. RHEL 9 in FIPS mode).
    """
    for d in include_dirs:
        header = os.path.join(d, 'xmlsec', 'keysdata.h')
        if os.path.exists(header):
            return 'xmlSecKeyDataFormatEngine' in open(header).read()
    return False


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default

    return value.strip().lower() not in {'', '0', 'false', 'no', 'off'}


class build_ext(build_ext_orig):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.debug = _env_flag('PYXMLSEC_ENABLE_DEBUG', False)
        self.static = _env_flag('PYXMLSEC_STATIC_DEPS', False)
        self.size_opt = _env_flag('PYXMLSEC_OPTIMIZE_SIZE', True)

    def info(self, message) -> None:
        self.announce(message, level=log.INFO)

    def run(self) -> None:
        ext = self.ext_map['xmlsec']
        if self.static or sys.platform == 'win32':
            helper = StaticBuildHelper(self)
            helper.prepare(sys.platform)
        else:
            import pkgconfig

            try:
                config = pkgconfig.parse('xmlsec1')
            except OSError as error:
                raise DistutilsError('Unable to invoke pkg-config.') from error
            except pkgconfig.PackageNotFoundError as error:
                raise DistutilsError('xmlsec1 is not installed or not in path.') from error

            if config is None or not config.get('libraries'):
                raise DistutilsError('Bad or incomplete result returned from pkg-config.')

            ext.define_macros.extend(config['define_macros'])
            ext.include_dirs.extend(config['include_dirs'])
            ext.library_dirs.extend(config['library_dirs'])
            ext.libraries.extend(config['libraries'])

            if _has_xmlsec_engine(ext.include_dirs):
                ext.define_macros.append(('PYXMLSEC_HAVE_XMLSEC_ENGINE', '1'))
                self.info('xmlSecKeyDataFormatEngine detected: ENGINE key loading enabled')
            else:
                self.info('xmlSecKeyDataFormatEngine not found: Key.from_engine() will raise xmlsec.Error at runtime')

        import lxml

        ext.include_dirs.extend(lxml.get_include())

        ext.define_macros.extend(
            [('MODULE_NAME', self.distribution.metadata.name), ('MODULE_VERSION', self.distribution.metadata.version)]
        )
        for key, value in ext.define_macros:
            if key == 'XMLSEC_CRYPTO' and not (value.startswith('"') and value.endswith('"')):
                ext.define_macros.remove((key, value))
                ext.define_macros.append((key, f'"{value}"'))
                break

        if sys.platform == 'win32':
            ext.extra_compile_args.append('/Zi')
        else:
            ext.extra_compile_args.extend(
                [
                    '-g',
                    '-std=c99',
                    '-fPIC',
                    '-fno-strict-aliasing',
                    '-Wno-error=declaration-after-statement',
                    '-Werror=implicit-function-declaration',
                ]
            )

        if self.debug:
            ext.define_macros.append(('PYXMLSEC_ENABLE_DEBUG', '1'))
            if sys.platform == 'win32':
                ext.extra_compile_args.append('/Od')
            else:
                ext.extra_compile_args.append('-Wall')
                ext.extra_compile_args.append('-O0')
        else:
            if self.size_opt:
                if sys.platform == 'win32':
                    ext.extra_compile_args.append('/Os')
                else:
                    ext.extra_compile_args.append('-Os')

        super().run()


__all__ = ('CrossCompileInfo', 'build_ext')
