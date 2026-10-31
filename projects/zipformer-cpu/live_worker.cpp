// CPU streaming experiment: PCM stays in memory; no device or file capture.
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include <sys/resource.h>
#include <sys/prctl.h>
#include <unistd.h>
#include <signal.h>
#include <time.h>
#include "nlohmann/json.hpp"
#include "sherpa-ncnn/csrc/recognizer.h"

using Json=nlohmann::json;
static double now() { timespec t{}; clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9; }
static void check(bool ok,const char *message) { if(!ok)throw std::runtime_error(message); }
static void emit(const Json &value) {std::cout<<value.dump()<<std::endl;}

int main(int argc,char **argv) {
    rlimit limit{0,0};setrlimit(RLIMIT_CORE,&limit);
    const auto parent=getppid();prctl(PR_SET_PDEATHSIG,SIGTERM);if(getppid()!=parent)return 3;alarm(180);
    try {
        check(argc==2||argc==3,"Provide model directory and optional decoder");
        const std::string decoder=argc==3?argv[2]:"greedy_search";
        check(decoder=="greedy_search"||decoder=="modified_beam_search","Unsupported decoder");
        const std::filesystem::path directory(argv[1]);
        sherpa_ncnn::RecognizerConfig config;
        auto &m=config.model_config;m.use_vulkan_compute=false;
        for(auto *o:{&m.encoder_opt,&m.decoder_opt,&m.joiner_opt}) {
            o->num_threads=4;o->use_vulkan_compute=false;
            o->use_fp16_packed=o->use_fp16_storage=o->use_fp16_arithmetic=o->use_fp16_uniform=false;
            o->use_int8_packed=o->use_int8_storage=o->use_int8_arithmetic=o->use_int8_uniform=false;
            o->use_subgroup_ops=false;o->use_cooperative_matrix=false;
        }
        m.tokens=(directory/"tokens.txt").string();
        m.encoder_param=(directory/"encoder_jit_trace-pnnx.ncnn.param").string();
        m.encoder_bin=(directory/"encoder_jit_trace-pnnx.ncnn.bin").string();
        m.decoder_param=(directory/"decoder_jit_trace-pnnx.ncnn.param").string();
        m.decoder_bin=(directory/"decoder_jit_trace-pnnx.ncnn.bin").string();
        m.joiner_param=(directory/"joiner_jit_trace-pnnx.ncnn.param").string();
        m.joiner_bin=(directory/"joiner_jit_trace-pnnx.ncnn.bin").string();
        config.decoder_config.method=decoder;config.decoder_config.num_active_paths=4;config.enable_endpoint=true;
        config.endpoint_config.rule1=sherpa_ncnn::EndpointRule(false,2.4,0);
        config.endpoint_config.rule2=sherpa_ncnn::EndpointRule(true,.3,0);
        config.endpoint_config.rule3=sherpa_ncnn::EndpointRule(false,0,20);
        const double load=now();sherpa_ncnn::Recognizer recognizer(config);
        emit({{"ready",true},{"execution_device","cpu"},{"decoder",decoder},{"model_load_seconds",now()-load}});
        std::unique_ptr<sherpa_ncnn::Stream> stream;
        std::vector<std::string> segments;
        int rate=0;size_t frames=0;double final_time=0,busy=0,maximum_call=0;
        auto state=[&]() {
            const std::string pending=stream?recognizer.GetResult(stream.get()).text:"";
            std::string text;for(const auto &s:segments){if(!text.empty())text+=' ';text+=s;}
            if(!pending.empty()){if(!text.empty())text+=' ';text+=pending;}
            rusage usage{};getrusage(RUSAGE_SELF,&usage);
            return Json{{"text",text},{"decoder",decoder},{"segments",segments.size()},{"input_frames",frames},
                {"sample_rate",rate},{"natural_final_proven",!segments.empty()&&pending.empty()},
                {"final_monotonic",final_time>0?Json(final_time):Json(nullptr)},
                {"pending_text",!pending.empty()},{"processing_seconds",busy},
                {"maximum_processing_call_seconds",maximum_call},{"peak_rss_kib",usage.ru_maxrss},
                {"input_finished_called",false}};
        };
        char buffer[65537];
        while(std::cin.getline(buffer,sizeof(buffer))) {
            auto request=Json::parse(buffer);const std::string op=request.at("op");
            if(op=="begin") {
                rate=request.at("rate");check(rate==16000||rate==48000,"Unsupported sample rate");
                stream=recognizer.CreateStream();segments.clear();frames=0;final_time=busy=maximum_call=0;
                emit({{"ready",true},{"execution_device","cpu"}});
            } else if(op=="audio") {
                check(bool(stream),"Begin stream first");
                auto samples=request.at("samples").get<std::vector<float>>();
                check(!samples.empty()&&samples.size()<=size_t(rate/10),"PCM block exceeds 100 ms");
                check(frames+samples.size()<=size_t(rate*35),"Finite audio limit exceeded");
                for(float x:samples)check(std::isfinite(x)&&std::abs(x)<=1.00001f,"Invalid normalized PCM");
                frames+=samples.size();const double start=now();
                // The upstream stream performs stateful resampling when rate != 16000.
                stream->AcceptWaveform(rate,samples.data(),static_cast<int>(samples.size()));
                int steps=0;
                while(recognizer.IsReady(stream.get())) {
                    check(++steps<10000,"Decode progress limit");recognizer.DecodeStream(stream.get());
                    if(recognizer.IsEndpoint(stream.get())) {
                        auto text=recognizer.GetResult(stream.get()).text;
                        if(!text.empty()){segments.push_back(text);final_time=now();}
                        recognizer.Reset(stream.get());
                    }
                }
                const double elapsed=now()-start;busy+=elapsed;maximum_call=std::max(maximum_call,elapsed);
                emit(state());
            } else if(op=="finish") {
                check(bool(stream),"No active stream");emit(state());stream.reset();
            } else if(op=="close") return 0;
            else throw std::runtime_error("Unknown operation");
        }
        check(std::cin.eof(),"Oversized protocol line");
        return 0;
    } catch(const std::exception &error) {emit({{"error",error.what()}});return 2;}
}
