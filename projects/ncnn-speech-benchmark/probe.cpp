#include <algorithm>
#include <cmath>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include <sys/resource.h>
#include <sys/prctl.h>
#include <unistd.h>
#include <signal.h>
#include "gpu.h"
#include "command.h"
#include "layer.h"
#include "layer_type.h"
#include "modelbin.h"

static void require(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }

static void operation(const ncnn::VulkanDevice *device, bool matmul, int k) {
    const int m = 16, n = 24;
    ncnn::Mat a(k, m), b(matmul ? n : k, matmul ? k : m);
    for (size_t i=0; i<a.total(); ++i) ((float*)a.data)[i] = ((int)(i%17)-8) / 16.f;
    for (size_t i=0; i<b.total(); ++i) ((float*)b.data)[i] = ((int)(i%13)-6) / 16.f;
    ncnn::Mat expected(matmul ? n : k, m);
    for (int y=0; y<m; ++y) for (int x=0; x<expected.w; ++x) {
        float value = 0;
        if (matmul) for (int t=0; t<k; ++t) value += a.row(y)[t] * b.row(t)[x];
        else value = a.row(y)[x] + b.row(y)[x];
        expected.row(y)[x] = value;
    }
    auto *layer = ncnn::create_layer_vulkan(matmul ? ncnn::LayerType::InnerProduct : ncnn::LayerType::BinaryOp);
    require(layer != nullptr, "Vulkan layer unavailable");
    ncnn::ParamDict parameters;
    parameters.set(0, matmul ? n : 0); // Dense output width, or ADD.
    std::vector<ncnn::Mat> weights;
    if(matmul) {
        parameters.set(1,0); parameters.set(2,n*k);
        weights.emplace_back(n*k);
        for(int out=0;out<n;++out) for(int in=0;in<k;++in)
            ((float*)weights[0].data)[out*k+in]=b.row(in)[out];
    }
    require(layer->load_param(parameters)==0, "Parameter load failed");
    require(layer->support_vulkan, "Layer would require CPU fallback");
    layer->vkdev = device;
    ncnn::ModelBinFromMatArray model(weights.data());
    require(layer->load_model(model)==0, "Weight load failed");
    ncnn::Option opt;
    opt.num_threads=1; opt.use_vulkan_compute=true; opt.use_packing_layout=false;
    opt.use_fp16_packed=opt.use_fp16_storage=opt.use_fp16_arithmetic=opt.use_fp16_uniform=false;
    opt.use_int8_packed=opt.use_int8_storage=opt.use_int8_arithmetic=opt.use_int8_uniform=false;
    opt.use_cooperative_matrix=false; opt.use_subgroup_ops=false;
    auto *blob=device->acquire_blob_allocator(); auto *staging=device->acquire_staging_allocator();
    ncnn::VkWeightAllocator weight_allocator(device);
    ncnn::VkWeightStagingAllocator weight_staging(device);
    opt.blob_vkallocator=opt.workspace_vkallocator=blob; opt.staging_vkallocator=staging;
    require(layer->create_pipeline(opt)==0 && layer->support_vulkan, "GPU pipeline creation failed");
    {
        ncnn::VkTransfer upload(device);
        auto weight_options=opt;
        weight_options.blob_vkallocator=weight_options.workspace_vkallocator=&weight_allocator;
        weight_options.staging_vkallocator=&weight_staging;
        require(layer->upload_model(upload,weight_options)==0 && upload.submit_and_wait()==0,"GPU weight upload failed");
    }
    float maximum_error=0, magnitude=0;
    {
        ncnn::VkCompute commands(device);
        std::vector<ncnn::VkMat> inputs(matmul ? 1 : 2), outputs(1);
        commands.record_upload(a, inputs[0], opt);
        int status=0;
        if(matmul) status=layer->forward(inputs[0],outputs[0],commands,opt);
        else {
            commands.record_upload(b,inputs[1],opt);
            status=layer->forward(inputs,outputs,commands,opt);
        }
        require(status==0, "Vulkan forward failed");
        require(!outputs[0].empty(), "GPU output absent");
        ncnn::Mat result;
        commands.record_download(outputs[0], result, opt);
        require(commands.submit_and_wait()==0, "Vulkan submission failed");
        require(result.w==expected.w && result.h==expected.h && result.elempack==1, "GPU output shape differs");
        for(size_t i=0; i<expected.total(); ++i) {
            const float actual=((float*)result.data)[i], want=((float*)expected.data)[i];
            require(std::isfinite(actual), "Non-finite GPU result");
            maximum_error=std::max(maximum_error,std::abs(actual-want)); magnitude=std::max(magnitude,std::abs(want));
        }
    }
    layer->destroy_pipeline(opt); delete layer;
    device->reclaim_blob_allocator(blob); device->reclaim_staging_allocator(staging);
    require(magnitude>0 && maximum_error<=0.0002f, "GPU result failed CPU reference");
    std::cout << "{\"kind\":\"gpu_operation\",\"operation\":\"" << (matmul ? "InnerProduct_MATRIX" : "BinaryOp_ADD")
              << "\",\"k\":" << k << ",\"direct_vkmat\":true,\"submitted\":true,\"max_error\":"
              << maximum_error << ",\"elements\":" << expected.total() << ",\"passed\":true}" << std::endl;
}

int main() {
    rlimit limit{0,0}; setrlimit(RLIMIT_CORE,&limit);
    const auto parent=getppid(); prctl(PR_SET_PDEATHSIG,SIGTERM);
    if(getppid()!=parent) return 3;
    alarm(180);
    try {
        require(ncnn::create_gpu_instance()==0, "Vulkan instance unavailable");
        require(ncnn::get_gpu_count()==1, "Expected only the forced hardware ICD");
        const auto &info=ncnn::get_gpu_info(0);
        require(info.type()==1 && std::string(info.device_name()).find("Adreno")!=std::string::npos,
                "Hardware Adreno required; software renderer refused");
        std::cout << "{\"kind\":\"device\",\"name\":\"" << info.device_name() << "\",\"hardware\":true,\"shared_memory\":"
                  << info.max_shared_memory_size() << ",\"api_version\":" << info.api_version() << "}" << std::endl;
        const auto *device=ncnn::get_gpu_device(0);
        require(device!=nullptr, "GPU logical device unavailable");
        operation(device,false,32);
        for(int k : {16,32,64}) operation(device,true,k);
        ncnn::destroy_gpu_instance();
        std::cout << "{\"kind\":\"probe_complete\",\"passed\":true}" << std::endl;
        return 0;
    } catch(const std::exception &error) {
        std::cerr << "NCNN_PROBE_FAILED: " << error.what() << std::endl;
        return 2;
    }
}
