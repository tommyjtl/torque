"""GPU presence/compile flags alone must not count as GPU execution."""
import importlib.util
from pathlib import Path
import unittest
import tempfile

path = Path(__file__).resolve().parents[1] / 'projects/whisper-gpu-benchmark/evidence.py'
spec = importlib.util.spec_from_file_location('gpu_benchmark_evidence', path)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)
embed_path = path.with_name('embed_spirv.py')
embed_spec = importlib.util.spec_from_file_location('gpu_benchmark_embed', embed_path)
embedding = importlib.util.module_from_spec(embed_spec)
embed_spec.loader.exec_module(embedding)
compat_spec = importlib.util.spec_from_file_location('gpu_benchmark_compat', path.with_name('apply_compat.py'))
compat = importlib.util.module_from_spec(compat_spec)
compat_spec.loader.exec_module(compat)


class GPUEvidenceTests(unittest.TestCase):
    def test_software_vulkan_device_is_rejected(self):
        rows = [{'kind': 'devices', 'devices': [{'gpu': True, 'description': 'llvmpipe'}]}]
        self.assertFalse(evidence.adreno_device(rows))

    def test_gpu_enumeration_and_build_flag_are_insufficient(self):
        rows = [{'kind': 'devices', 'devices': [{'gpu': True, 'description': 'Turnip Adreno 702'}]}]
        self.assertFalse(evidence.gpu_execution(rows, 'VULKAN = 1')['accepted'])

    def test_backend_buffers_and_profile_are_required_for_profiled_smoke(self):
        rows = [{'kind': 'devices', 'devices': [{'gpu': True, 'description': 'Turnip Adreno 702'}]}]
        log = 'whisper_backend_init_gpu: using Vulkan0 backend\nwhisper_model_load: Vulkan0 total size = 77.0 MB\n'
        self.assertFalse(evidence.gpu_execution(rows, log, require_profile=True)['accepted'])
        self.assertFalse(evidence.gpu_execution(rows, log + 'Vulkan Timings:', require_profile=True)['accepted'])
        self.assertTrue(evidence.gpu_execution(rows, log + 'Vulkan Timings:\nMUL_MAT: 2 x 100 us = 200 us', require_profile=True)['accepted'])
        self.assertFalse(evidence.gpu_execution(rows, log + 'device lost')['accepted'])

    def test_malformed_native_output_is_reported_instead_of_hidden(self):
        rows, errors = evidence.parse_rows('{"kind":"devices","devices":[]}\npartial output\n')
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(errors), 1)

    def test_binary_embedding_preserves_bytes_and_pointer_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'vulkan-shaders.spv').mkdir()
            data = bytes([3, 2, 35, 7, 0, 255, 16, 1])
            binary = root / 'vulkan-shaders.spv/test.spv'
            binary.write_bytes(data)
            source = root / 'test.comp.cpp'
            source.write_text('const uint64_t test_len = 8;\nconst unsigned char test_data[8] = {\n'
                              '0x3,0x2,0x23,0x7,0x0,0xff,0x10,0x1,\n};\nconst void * table[1] = {test_data};\n')
            target, receipt = root / 'output.cpp', root / 'receipt.json'
            embedding.convert(source, target, receipt)
            self.assertIn('const uint64_t test_len = 8;', target.read_text())
            self.assertIn('const void * table[1] = {test_data};', target.read_text())
            self.assertIn('.incbin', target.read_text())
            self.assertNotIn('0xff', target.read_text())
            binary.write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError, 'identity'):
                embedding.convert(source, target, receipt)

    def test_compatibility_patch_keeps_resource_check_and_adds_cpu_fallback(self):
        original = 'if (!ggml_vk_matmul_shmem_support(device, s_warptile_mmq, false, t)) {\n' + compat.OLD + '\n}\n' + compat.GUARD
        result = compat.patched(original)
        self.assertIn('if (!ggml_vk_matmul_shmem_support', result)
        self.assertIn('device->mul_mat_s[i] = device->mul_mat_m[i] = device->mul_mat_l[i] = false;', result)
        self.assertIn('return false; // Unsupported dtype must be scheduled on CPU.', result)
        self.assertIn('continue;', result)
        with self.assertRaisesRegex(ValueError, 'reviewed'):
            compat.patched('unreviewed source')
