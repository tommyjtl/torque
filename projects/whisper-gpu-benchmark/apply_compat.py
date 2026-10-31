"""Private, bounded compatibility patch: unsupported dtypes fall back to CPU."""
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RELATIVE = 'ggml/src/ggml-vulkan/ggml-vulkan.cpp'
OLD = '''                std::cerr << "ggml_vulkan: Error: Shared memory size too small for matrix multiplication." << std::endl;
                throw std::runtime_error("Shared memory size too small for matrix multiplication.");'''
NEW = '''                // Private 16-KiB compatibility: reject this dtype, not all dtypes.
                device->mul_mat_s[i] = device->mul_mat_m[i] = device->mul_mat_l[i] = false;
                device->mul_mat_id_s[i] = device->mul_mat_id_m[i] = device->mul_mat_id_l[i] = false;
                device->mul_mat_s_int[i] = device->mul_mat_m_int[i] = device->mul_mat_l_int[i] = false;
                device->mul_mat_id_s_int[i] = device->mul_mat_id_m_int[i] = device->mul_mat_id_l_int[i] = false;
                std::cerr << "ggml_vulkan: disabling unsupported shared-memory dtype " << ggml_type_name(t) << std::endl;
                continue;'''
GUARD = '''                ggml_type src0_type = op->src[0]->type;
                if (op->op == GGML_OP_MUL_MAT_ID) {'''
GUARDED = '''                ggml_type src0_type = op->src[0]->type;
                if (op->op == GGML_OP_MUL_MAT &&
                    !device->mul_mat_s[src0_type] && !device->mul_mat_m[src0_type] && !device->mul_mat_l[src0_type]) {
                    return false; // Unsupported dtype must be scheduled on CPU.
                }
                if (op->op == GGML_OP_MUL_MAT_ID) {'''


def patched(text):
    if text.count(OLD) != 1 or text.count(GUARD) != 1:
        raise ValueError('Source does not match the reviewed pinned backend')
    return text.replace(OLD, NEW).replace(GUARD, GUARDED)


def main():
    source = ROOT / 'vendor/whisper.cpp' / RELATIVE
    old = source.read_text()
    new = patched(old)
    patch = ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                       fromfile='a/' + RELATIVE, tofile='b/' + RELATIVE))
    (ROOT / 'vulkan-low-memory.patch').write_text(patch)
    source.write_text(new)
    metadata = json.loads((ROOT / 'source-lock.json').read_text())
    metadata['private_compatibility_patch'] = {'file': 'vulkan-low-memory.patch',
        'sha256': hashlib.sha256(patch.encode()).hexdigest(),
        'before_cpp_sha256': hashlib.sha256(old.encode()).hexdigest(),
        'after_cpp_sha256': hashlib.sha256(new.encode()).hexdigest(),
        'purpose': 'Disable dtypes whose smallest tile exceeds real shared memory; retain all resource checks and CPU fallback'}
    (ROOT / 'source-lock.json').write_text(json.dumps(metadata, indent=2))
    print('PRIVATE_COMPATIBILITY_PATCH_READY')


if __name__ == '__main__':
    main()
