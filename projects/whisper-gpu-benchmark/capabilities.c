/* Query the feature structures used by the pinned backend, without dispatch. */
#include <stdio.h>
#include <vulkan/vulkan.h>

int main(void) {
    VkApplicationInfo app = { .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
                             .pApplicationName = "Torque GPU capability check", .apiVersion = VK_API_VERSION_1_2 };
    VkInstanceCreateInfo create = { .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app };
    VkInstance instance;
    VkResult result = vkCreateInstance(&create, NULL, &instance);
    if (result != VK_SUCCESS) return 2;
    VkPhysicalDevice devices[8];
    uint32_t count = 8;
    result = vkEnumeratePhysicalDevices(instance, &count, devices);
    if (result != VK_SUCCESS || count == 0) return 3;
    for (uint32_t i = 0; i < count; ++i) {
        VkPhysicalDeviceProperties properties;
        vkGetPhysicalDeviceProperties(devices[i], &properties);
        VkPhysicalDeviceVulkan11Features core = { .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_FEATURES };
        VkPhysicalDeviceFeatures2 features = { .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext = &core };
        vkGetPhysicalDeviceFeatures2(devices[i], &features);
        VkPhysicalDevice16BitStorageFeatures storage = { .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_16BIT_STORAGE_FEATURES };
        features.pNext = &storage;
        vkGetPhysicalDeviceFeatures2(devices[i], &features);
        printf("{\"device\":\"%s\",\"vulkan11_storage16\":%u,\"extension_storage16\":%u,\"api_version\":%u}\n",
               properties.deviceName, core.storageBuffer16BitAccess, storage.storageBuffer16BitAccess, properties.apiVersion);
    }
    vkDestroyInstance(instance, NULL);
    return 0;
}
