"""Private C++ wrapper: replace only huge data-only shader literal arrays."""
import os
from pathlib import Path
import sys
from embed_spirv import convert

ROOT = Path(__file__).resolve().parent


def main():
    driver, *arguments = sys.argv[1:]
    scratch = ROOT / 'scratch/embedded-spv'
    scratch.mkdir(exist_ok=True)
    for i, argument in enumerate(arguments):
        source = Path(argument)
        if source.name.endswith('.comp.cpp') and source.is_file() and source.stat().st_size > 8 * 1024**2:
            if not source.resolve().is_relative_to(ROOT / 'build'):
                raise ValueError('Generated source is outside this experiment')
            target = scratch / source.name
            convert(source, target, target.with_suffix('.receipt.json'))
            arguments[i] = str(target)
    os.execve(driver, [driver, '--sysroot=' + str(ROOT / 'tools'), *arguments], os.environ)


if __name__ == '__main__':
    main()
