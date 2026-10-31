"""Make diagnostic timestamps/logging opt-in; leave tensor operations unchanged."""
import difflib
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def main():
    path = ROOT / 'vendor/ncnn/src/net.cpp'
    before = path.read_text()
    if 'torque_profile_enabled' in before:
        print('PROFILE_CONTROL_ALREADY_APPLIED')
        return
    after = before.replace('#include "net.h"', '#include "net.h"\n#include <cstdlib>', 1)
    after = after.replace('namespace ncnn {', '''namespace ncnn {
// Private benchmark control: no model/operator math is changed.
static bool torque_profile_enabled() {
    static const bool enabled = [] { const char* p = std::getenv("TORQUE_NCNN_PROFILE"); return p && p[0] == '1'; }();
    return enabled;
}
''', 1)
    assert after != before and 'static bool torque_profile_enabled()' in after
    for function in ('record_write_timestamp', 'create_query_pool', 'get_query_pool_results'):
        token = 'cmd.' + function + '('
        assert token in after
        after = after.replace(token, 'if (torque_profile_enabled()) ' + token)
    for variable in ('start', 'end'):
        token = 'double ' + variable + ' = get_current_time();'
        assert after.count(token) == 2
        after = after.replace(token, 'double ' + variable + ' = torque_profile_enabled() ? get_current_time() : 0;')
    after, count = re.subn(r'(?m)^(\s*)benchmark\(', r'\1if (torque_profile_enabled()) benchmark(', after)
    assert count == 4
    patch = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        fromfile='a/src/net.cpp', tofile='b/src/net.cpp'))
    (ROOT / 'runtime-profile.patch').write_text(patch)
    lock = json.loads((ROOT / 'source-lock.json').read_text())
    lock['runtime_profile_control'] = {'before_sha256': hashlib.sha256(before.encode()).hexdigest(),
        'after_sha256': hashlib.sha256(after.encode()).hexdigest(),
        'patch_sha256': hashlib.sha256(patch.encode()).hexdigest(),
        'description': 'Only diagnostic timestamp/query/log statements are conditional; no tensor operations changed'}
    path.write_text(after)
    (ROOT / 'source-lock.json').write_text(json.dumps(lock, indent=2))
    print('OPTIONAL_DIAGNOSTICS_READY')


if __name__ == '__main__':
    main()
