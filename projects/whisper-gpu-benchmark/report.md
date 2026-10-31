# UNO Q Whisper Vulkan experiment

**No accepted GPU transcription timing was obtained.** The stock backend rejected the GPU at initialization. A private compatibility patch allowed model allocation, but profiled, unprofiled and conservative FP32/fusion-off inference all aborted with Vulkan device loss before a completed transcript.

The actual Adreno 702 was selected through the Freedreno ICD. llvmpipe was excluded. Enumeration, context initialization and GPU model-buffer allocation are not treated as completed GPU inference.

| Run | Configuration | Result | Valid measured transcripts |
| --- | --- | --- | --- |
| 20261030T051525-probe | probe | passed | 0 |
| 20261030T051556-cpu | cpu | passed | 1 |
| 20261030T051657-gpu-profile | gpu / profile | Shared-memory initialization refused | 0 |
| 20261030T053840-gpu-profile | gpu / profile | ErrorDeviceLost | 0 |
| 20261030T054831-gpu | gpu | ErrorDeviceLost | 0 |
| 20261030T055100-gpu | gpu / GGML_VK_DISABLE_F16=1, GGML_VK_DISABLE_FUSION=1 | ErrorDeviceLost | 0 |
| 20261030T055333-cpu | cpu | passed | 18 |

Matched-build CPU control: original Tiny English weights, four threads, one excluded warm-up and three warm repetitions for each of the same six clips.

Median full decode: **5.278 s**, range 5.003–6.046 s. Aggregate RTF: 0.702. WER on six unique clips: 2/136 = 1.5%. Peak native-process RSS: 165.3 MiB.

| Clip duration | CPU median decode | WER |
| --- | --- | --- |
| 3.505 s | 5.007 s | 0.0% |
| 5.850 s | 5.183 s | 0.0% |
| 13.160 s | 5.728 s | 0.0% |
| 6.285 s | 5.332 s | 4.5% |
| 3.855 s | 5.130 s | 0.0% |
| 13.585 s | 6.024 s | 2.3% |

The GPU shared-memory limit is 16 KiB **per workgroup**, not the total memory available for the model. The reviewed small IQ1 tile needs 16,512 bytes, while the conservative F16 check needs 4,224 bytes. The private patch disables unsupported dtypes and adds CPU scheduling fallback; it does not raise the hardware limit or alter shader/model bytes.

A 140 MB generated C++ shader-literal file exceeded build memory with parallel compilation. Large literal arrays were instead embedded from their original SPIR-V files, with per-array SHA-256 identity checks and a native link/byte test. This is build packaging, not a math optimization.

No microphone was opened. This experiment does not demonstrate sub-one-second final speech recognition or a GPU speedup. Further GPU work requires backend/driver kernel compatibility debugging, rather than changing MCU firmware or merely enabling a GPU option.
