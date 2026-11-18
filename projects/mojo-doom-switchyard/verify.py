"""Run bounded native replay/save checks. Pass --iwad to also test original E1M1."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    parser.add_argument('--iwad', type=Path)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    exe = args.exe.resolve()
    args.evidence.mkdir(parents=True, exist_ok=True)
    summary = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, media in [('fixture', ['--fixture'])] + ([('e1m1', ['--iwad', str(args.iwad),
                '--index', str(args.iwad.with_suffix('.syi'))])] if args.iwad else []):
            def run(label, options):
                result = subprocess.run([str(exe), *media, *options], cwd=tmp, text=True,
                                        capture_output=True, timeout=25)
                (args.evidence / f'{name}-{label}.log').write_text(result.stderr + result.stdout)
                result.check_returncode()
                return result.stdout
            run('check', ['--check'])
            reference = None
            for backend, other in [('cpu', 'gpu'), ('gpu', 'cpu')]:
                save = Path(tmp) / f'{name}-{backend}.sav'
                full = run(backend, [f'--renderer={backend}', '--tour', '--save', str(save),
                                     '--capture', str((args.evidence/f'{name}-{backend}.ppm').resolve())])
                resumed = run(f'{other}-from-{backend}', [f'--renderer={other}', '--tour',
                              '--save', str(save), '--resume', '--seconds', '4', '--mute'])
                def state(text):return re.search(r'state=([0-9a-f]+)', text)[1]
                assert state(full) == state(resumed), (full,resumed)
                assert reference in (None,state(full)), full
                reference = state(full)
                if name == 'fixture': assert 'signal=1 exit=1' in full
                else: assert 'ammo=49' in full
                assert int(re.search(r'audio_blocks=(\d+)',full)[1])>0, full
            assert (Path(tmp)/f'{name}-cpu.sav').read_bytes()==(Path(tmp)/f'{name}-gpu.sav').read_bytes()
            summary[name]={'final_state':reference,'both_backends':True,'cross_load':True}
    print(json.dumps(summary))


if __name__ == '__main__':main()
