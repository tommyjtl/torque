#include <algorithm>
#include <chrono>
#include <filesystem>
#include <iostream>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <sys/resource.h>
#include <sys/prctl.h>
#include <unistd.h>
#include <signal.h>
#include "nlohmann/json.hpp"
#include "gpu.h"
#include "sherpa-ncnn/csrc/recognizer.h"
#include "sherpa-ncnn/csrc/wave-reader.h"

using Clock=std::chrono::steady_clock;
using Json=nlohmann::json;
static double elapsed(Clock::time_point start) { return std::chrono::duration<double>(Clock::now()-start).count(); }
static void require(bool ok,const char *message) { if(!ok) throw std::runtime_error(message); }
static void emit(const Json &row) { std::cout << row.dump() << std::endl; }
static double cpu_seconds(const rusage &u) { return u.ru_utime.tv_sec+u.ru_utime.tv_usec/1e6+u.ru_stime.tv_sec+u.ru_stime.tv_usec/1e6; }

static Json trial(sherpa_ncnn::Recognizer &recognizer, const char *path, bool paced, int repeat) {
    bool ok=false;
    auto samples=sherpa_ncnn::ReadWave(std::string(path),16000,&ok);
    require(ok && !samples.empty() && samples.size()<=30*16000, "Invalid bounded PCM input");
    const double duration=samples.size()/16000.0;
    const size_t frames=samples.size();
    samples.resize(frames+3*16000,0.f);
    auto stream=recognizer.CreateStream();
    std::vector<std::string> segments;
    std::vector<double> endpoints;
    std::optional<double> final_at,first_text;
    double maximum_lag=0,maximum_call=0,busy=0;
    rusage before{},after{};getrusage(RUSAGE_SELF,&before);
    const auto start=Clock::now();
    for(size_t position=0;position<samples.size();position+=320) {
        const size_t count=std::min(size_t(320),samples.size()-position);
        const double scheduled=(position+count)/16000.0;
        if(paced) std::this_thread::sleep_until(start+std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(scheduled)));
        if(paced) maximum_lag=std::max(maximum_lag,elapsed(start)-scheduled);
        auto call=Clock::now();
        stream->AcceptWaveform(16000,samples.data()+position,static_cast<int>(count));
        int iterations=0;
        while(recognizer.IsReady(stream.get())) {
            require(++iterations<10000,"Decode progress limit");
            recognizer.DecodeStream(stream.get());
            const auto current=recognizer.GetResult(stream.get());
            if(!current.text.empty() && !first_text) first_text=elapsed(start);
            if(recognizer.IsEndpoint(stream.get())) {
                if(!current.text.empty()) {
                    segments.push_back(current.text);
                    final_at=elapsed(start); endpoints.push_back(*final_at);
                }
                recognizer.Reset(stream.get());
            }
        }
        const double call_seconds=elapsed(call);
        busy+=call_seconds;maximum_call=std::max(maximum_call,call_seconds);
    }
    const auto pending=recognizer.GetResult(stream.get()).text;
    std::string text;
    for(const auto &segment:segments) { if(!text.empty())text+=' ';text+=segment; }
    if(!pending.empty()) { if(!text.empty())text+=' ';text+=pending; }
    const bool accepted=final_at.has_value() && pending.empty() && !text.empty();
    getrusage(RUSAGE_SELF,&after);
    Json row={{"kind",repeat<0 ? "warmup":"file"},{"path",path},{"repeat",repeat},
        {"text",text},{"audio_seconds",duration},{"wall_seconds",elapsed(start)},
        {"processing_seconds",busy},{"maximum_processing_call_seconds",maximum_call},
        {"maximum_input_lag_seconds",maximum_lag},{"cpu_seconds",cpu_seconds(after)-cpu_seconds(before)},
        {"peak_rss_kib",after.ru_maxrss},{"natural_final_proven",accepted},
        {"pending_text_after_trailing_silence",!pending.empty()},{"endpoint_times",endpoints},
        {"paced",paced},{"input_finished_called",false},{"reference_speech_end_latency",nullptr}};
    row["file_end_to_final_seconds"]=paced && accepted ? Json(*final_at-duration):Json(nullptr);
    row["first_text_from_start_seconds"]=first_text ? Json(*first_text):Json(nullptr);
    return row;
}

int main(int argc,char **argv) {
    rlimit limit{0,0};setrlimit(RLIMIT_CORE,&limit);
    const auto parent=getppid();prctl(PR_SET_PDEATHSIG,SIGTERM);if(getppid()!=parent)return 3;alarm(1200);
    try {
        require(argc>=6,"Use cpu|gpu MODEL_DIR REPEATS paced|bulk WAV...");
        const bool gpu=std::string(argv[1])=="gpu",paced=std::string(argv[4])=="paced";
        require(gpu || std::string(argv[1])=="cpu","Unknown execution device");
        require(paced || std::string(argv[4])=="bulk","Unknown pacing mode");
        const int repeats=std::stoi(argv[3]);require(repeats>=1 && repeats<=3,"Repeat limit");
        if(gpu) {
            require(ncnn::create_gpu_instance()==0 && ncnn::get_gpu_count()==1,"Expected forced hardware GPU");
            const auto &info=ncnn::get_gpu_info(0);
            require(info.type()==1 && std::string(info.device_name()).find("Adreno")!=std::string::npos,"Hardware Adreno required");
            emit({{"kind","device"},{"name",info.device_name()},{"hardware",true}});
        }
        sherpa_ncnn::RecognizerConfig config;
        auto &model=config.model_config;
        model.use_vulkan_compute=gpu;
        for(auto *option:{&model.encoder_opt,&model.decoder_opt,&model.joiner_opt}) {
            option->num_threads=4;option->use_vulkan_compute=gpu;
            option->use_fp16_packed=option->use_fp16_storage=option->use_fp16_arithmetic=option->use_fp16_uniform=false;
            option->use_int8_packed=option->use_int8_storage=option->use_int8_arithmetic=option->use_int8_uniform=false;
            option->use_subgroup_ops=false;option->use_cooperative_matrix=false;
        }
        const std::filesystem::path directory(argv[2]);
        model.tokens=(directory/"tokens.txt").string();
        model.encoder_param=(directory/"encoder_jit_trace-pnnx.ncnn.param").string();
        model.encoder_bin=(directory/"encoder_jit_trace-pnnx.ncnn.bin").string();
        model.decoder_param=(directory/"decoder_jit_trace-pnnx.ncnn.param").string();
        model.decoder_bin=(directory/"decoder_jit_trace-pnnx.ncnn.bin").string();
        model.joiner_param=(directory/"joiner_jit_trace-pnnx.ncnn.param").string();
        model.joiner_bin=(directory/"joiner_jit_trace-pnnx.ncnn.bin").string();
        config.decoder_config.method="greedy_search";
        config.enable_endpoint=true;
        config.endpoint_config.rule1=sherpa_ncnn::EndpointRule(false,2.4,0);
        config.endpoint_config.rule2=sherpa_ncnn::EndpointRule(true,.3,0);
        config.endpoint_config.rule3=sherpa_ncnn::EndpointRule(false,0,20);
        const auto initialized=Clock::now();
        {
            sherpa_ncnn::Recognizer recognizer(config);
            emit({{"kind","initialization"},{"model_load_seconds",elapsed(initialized)},
                  {"gpu_requested",gpu},{"threads",4},{"endpoint_silence_seconds",.3},
                  {"fp16_compute",false},{"subgroup_ops",false},{"decoder","greedy_search"}});
            emit(trial(recognizer,argv[5],paced,-1));
            for(int repeat=0;repeat<repeats;++repeat)
                for(int i=5;i<argc;++i)emit(trial(recognizer,argv[i],paced,repeat));
        }
        if(gpu)ncnn::destroy_gpu_instance();
        emit({{"kind","speech_complete"},{"passed",true}});
        return 0;
    } catch(const std::exception &error) {
        emit({{"kind","failure"},{"error",error.what()}});
        return 2;
    }
}
