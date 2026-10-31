// Private full-transcription comparison; no device I/O beyond the GPU backend.
#include "whisper.h"
#include "ggml-backend.h"
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <sys/prctl.h>
#include <vector>

using Clock = std::chrono::steady_clock;

static std::string quoted(const std::string & text) {
    std::string result = "\"";
    for (unsigned char c : text) {
        if (c == '\\' || c == '"') result += '\\';
        if (c == '\n') result += "\\n";
        else if (c == '\r') result += "\\r";
        else if (c == '\t') result += "\\t";
        else if (c >= 32) result += static_cast<char>(c);
    }
    return result + '"';
}

static uint32_t u32(const unsigned char * p) {
    return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24;
}

static uint16_t u16(const unsigned char * p) {
    return uint16_t(p[0]) | uint16_t(p[1]) << 8;
}

static std::vector<float> wav(const std::string & name) {
    std::ifstream file(name, std::ios::binary);
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    if (bytes.size() < 44 || std::string(reinterpret_cast<char *>(bytes.data()), 4) != "RIFF" ||
        std::string(reinterpret_cast<char *>(bytes.data() + 8), 4) != "WAVE")
        throw std::runtime_error("Invalid WAV");
    bool format = false;
    for (size_t pos = 12; pos + 8 <= bytes.size();) {
        uint32_t size = u32(bytes.data() + pos + 4);
        if (size > bytes.size() - pos - 8) throw std::runtime_error("Truncated WAV");
        std::string type(reinterpret_cast<char *>(bytes.data() + pos), 4);
        auto * data = bytes.data() + pos + 8;
        if (type == "fmt ") {
            format = size >= 16 && u16(data) == 1 && u16(data + 2) == 1 &&
                     u32(data + 4) == 16000 && u16(data + 14) == 16;
        } else if (type == "data") {
            if (!format || size % 2 || size > 16000 * 2 * 30)
                throw std::runtime_error("Expected finite mono 16 kHz PCM16 WAV");
            std::vector<float> result(size / 2);
            for (size_t i = 0; i < result.size(); ++i)
                result[i] = static_cast<int16_t>(u16(data + i * 2)) / 32768.0f;
            return result;
        }
        pos += 8 + size + (size & 1);
    }
    throw std::runtime_error("WAV has no PCM data");
}

int main(int argc, char ** argv) {
    // Failed experimental GPU dispatch must not create a large core dump.
    rlimit core_limit{0, 0};
    setrlimit(RLIMIT_CORE, &core_limit);
    prctl(PR_SET_DUMPABLE, 0);
    try {
        if (argc < 2) throw std::runtime_error("Use probe, cpu or gpu");
        bool gpu = std::string(argv[1]) == "gpu";
        if (!gpu && std::string(argv[1]) != "cpu" && std::string(argv[1]) != "probe")
            throw std::runtime_error("Unknown mode");
        ggml_backend_load_all();
        bool adreno = false;
        std::cout << "{\"kind\":\"devices\",\"devices\":[";
        for (size_t i = 0; i < ggml_backend_dev_count(); ++i) {
            auto device = ggml_backend_dev_get(i);
            std::string description = ggml_backend_dev_description(device);
            auto type = ggml_backend_dev_type(device);
            bool hardware = type == GGML_BACKEND_DEVICE_TYPE_GPU || type == GGML_BACKEND_DEVICE_TYPE_IGPU;
            adreno |= hardware && description.find("Adreno") != std::string::npos;
            if (i) std::cout << ',';
            std::cout << "{\"name\":" << quoted(ggml_backend_dev_name(device))
                      << ",\"description\":" << quoted(description) << ",\"gpu\":"
                      << (hardware ? "true" : "false") << '}';
        }
        std::cout << "]}" << std::endl;
        if (std::string(argv[1]) == "probe") return adreno ? 0 : 3;
        if (gpu && !adreno) throw std::runtime_error("No hardware Adreno backend; CPU fallback refused");
        if (argc < 5) throw std::runtime_error("Use MODE MODEL REPEATS WAV...");
        int repeats = std::stoi(argv[3]);
        if (repeats < 1 || repeats > 3) throw std::runtime_error("Repeat limit");
        auto params = whisper_context_default_params();
        params.use_gpu = gpu;
        params.gpu_device = 0;
        auto start = Clock::now();
        std::unique_ptr<whisper_context, decltype(&whisper_free)> context(
            whisper_init_from_file_with_params(argv[2], params), whisper_free);
        if (!context) throw std::runtime_error("Model/backend initialization failed");
        std::cout << "{\"kind\":\"initialization\",\"gpu_requested\":" << (gpu ? "true" : "false")
                  << ",\"flash_attention_requested\":" << (params.flash_attn ? "true" : "false")
                  << ",\"seconds\":" << std::chrono::duration<double>(Clock::now() - start).count()
                  << ",\"system_info\":" << quoted(whisper_print_system_info()) << '}' << std::endl;
        auto decode = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
        decode.n_threads = 4;
        decode.greedy.best_of = 1;
        decode.language = "en";
        decode.translate = false;
        decode.no_context = true;
        decode.temperature = 0.0f;
        decode.temperature_inc = 0.0f;
        decode.print_progress = decode.print_realtime = decode.print_timestamps = false;
        for (int repeat = -1; repeat < repeats; ++repeat) {
            int end = repeat < 0 ? 5 : argc;
            for (int index = 4; index < end; ++index) {
                auto samples = wav(argv[index]);
                rusage before{}, after{};
                getrusage(RUSAGE_SELF, &before);
                start = Clock::now();
                int result = whisper_full(context.get(), decode, samples.data(), static_cast<int>(samples.size()));
                double elapsed = std::chrono::duration<double>(Clock::now() - start).count();
                getrusage(RUSAGE_SELF, &after);
                if (result != 0) throw std::runtime_error("Transcription failed");
                std::string text;
                for (int i = 0; i < whisper_full_n_segments(context.get()); ++i)
                    text += whisper_full_get_segment_text(context.get(), i);
                auto seconds = [](timeval value) { return value.tv_sec + value.tv_usec / 1e6; };
                std::cout << "{\"kind\":" << quoted(repeat < 0 ? "warmup" : "file")
                          << ",\"path\":" << quoted(argv[index]) << ",\"repeat\":" << repeat
                          << ",\"seconds\":" << elapsed << ",\"audio_seconds\":" << samples.size() / 16000.0
                          << ",\"cpu_seconds\":" << seconds(after.ru_utime) + seconds(after.ru_stime) - seconds(before.ru_utime) - seconds(before.ru_stime)
                          << ",\"peak_rss_kib\":" << after.ru_maxrss << ",\"text\":" << quoted(text)
                          << '}' << std::endl;
            }
        }
        return 0;
    } catch (const std::exception & error) {
        std::cerr << "Benchmark: " << error.what() << std::endl;
        return 2;
    }
}
