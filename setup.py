"""Bundle manifest-discovered reference files alongside the Torque Python package."""
import importlib.util
from pathlib import Path
import shutil
import sys
from setuptools import setup
from setuptools.command.build_py import build_py as BaseBuildPy

ROOT = Path(__file__).resolve().parent


def catalog():
    # The catalog parser uses only stdlib at import time, including in isolated
    # builds that have not installed the hardware SDK dependency yet.
    spec = importlib.util.spec_from_file_location('_torque_example_build', ROOT/'packages/session/src/torque/examples.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, module.discover(ROOT/'examples')


class BuildPy(BaseBuildPy):
    def run(self):
        # Update bundles can carry a build tree whose files share the source's
        # whole-second mtime. Never reuse those Python modules by timestamp.
        self.force = True
        super().run()
        module, entries = catalog()
        target = Path(self.build_lib).resolve()/'torque/_examples'
        if target.exists():
            if target.is_symlink():
                raise ValueError('Generated example data directory cannot be a symlink')
            shutil.rmtree(target)
        for entry in entries.values():
            for source in module.resource_files(entry):
                output = target/entry.directory.name/source.relative_to(entry.directory)
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, output)

    def get_source_files(self):
        module, entries = catalog()
        extra = [str(path.relative_to(ROOT)) for entry in entries.values() for path in module.resource_files(entry)]
        return [*super().get_source_files(), *extra]


setup(cmdclass={'build_py': BuildPy})
