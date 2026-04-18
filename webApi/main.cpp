#include <iostream>
#include <thread>
#include <atomic>
#include <mutex>
#include <chrono>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <deque>

#include "httplib.h"  // 需下载 httplib.h 到同目录

// ---------- 系统信息读取（Linux） ----------
struct CPUStats {
    unsigned long long user, nice, system, idle, iowait, irq, softirq, steal;
};

bool readCPUStats(CPUStats& stats) {
    std::ifstream file("/proc/stat");
    if (!file) return false;
    std::string line;
    std::getline(file, line);
    std::istringstream iss(line);
    std::string cpu;
    iss >> cpu;
    if (cpu != "cpu") return false;
    iss >> stats.user >> stats.nice >> stats.system >> stats.idle
        >> stats.iowait >> stats.irq >> stats.softirq >> stats.steal;
    return true;
}

float calculateCPULoad(const CPUStats& prev, const CPUStats& curr) {
    auto prevIdle = prev.idle + prev.iowait;
    auto currIdle = curr.idle + curr.iowait;
    auto prevTotal = prev.user + prev.nice + prev.system + prev.idle
                   + prev.iowait + prev.irq + prev.softirq + prev.steal;
    auto currTotal = curr.user + curr.nice + curr.system + curr.idle
                   + curr.iowait + curr.irq + curr.softirq + curr.steal;
    auto totalDiff = currTotal - prevTotal;
    auto idleDiff  = currIdle - prevIdle;
    if (totalDiff == 0) return 0.0f;
    return 100.0f * (1.0f - static_cast<float>(idleDiff) / totalDiff);
}

float readMemoryUsage() {
    std::ifstream file("/proc/meminfo");
    if (!file) return 0.0f;
    std::string line;
    unsigned long long memTotal = 0, memAvailable = 0;
    while (std::getline(file, line)) {
        std::istringstream iss(line);
        std::string key;
        unsigned long long value;
        iss >> key >> value;
        if (key == "MemTotal:") memTotal = value;
        else if (key == "MemAvailable:") memAvailable = value;
        if (memTotal && memAvailable) break;
    }
    if (memTotal == 0) return 0.0f;
    unsigned long long memUsed = memTotal - memAvailable;
    return 100.0f * memUsed / memTotal;
}

// ---------- 共享数据（线程安全） ----------
struct SystemMetrics {
    std::mutex mtx;
    float cpu_percent = 0.0f;
    float mem_percent = 0.0f;
};

// ---------- 简单滑动窗口限流器 ----------
class RateLimiter {
public:
    RateLimiter(int max_per_second) : max_per_sec(max_per_second) {}

    bool allow() {
        auto now = std::chrono::steady_clock::now();
        std::lock_guard<std::mutex> lock(mtx);
        // 移除超过1秒的旧记录
        while (!timestamps.empty() &&
               std::chrono::duration_cast<std::chrono::seconds>(now - timestamps.front()).count() >= 1) {
            timestamps.pop_front();
        }
        if (timestamps.size() < max_per_sec) {
            timestamps.push_back(now);
            return true;
        }
        return false;
    }

private:
    int max_per_sec;
    std::deque<std::chrono::steady_clock::time_point> timestamps;
    std::mutex mtx;
};

// ---------- 后台更新线程 ----------
void updaterThread(SystemMetrics& metrics, std::atomic<bool>& running) {
    CPUStats prev, curr;
    if (!readCPUStats(prev)) {
        std::cerr << "Failed to read initial CPU stats" << std::endl;
        return;
    }

    while (running) {
        std::this_thread::sleep_for(std::chrono::seconds(1));

        // 更新内存（瞬时值）
        float mem = readMemoryUsage();

        // 更新 CPU（差值计算）
        if (readCPUStats(curr)) {
            float cpu = calculateCPULoad(prev, curr);
            {
                std::lock_guard<std::mutex> lock(metrics.mtx);
                metrics.cpu_percent = cpu;
                metrics.mem_percent = mem;
            }
            prev = curr;
        }
    }
}

// ---------- 主函数 ----------
int main() {
    SystemMetrics metrics;
    std::atomic<bool> running{true};

    // 启动后台更新线程
    std::thread updater(updaterThread, std::ref(metrics), std::ref(running));

    // 创建 HTTP 服务器
    httplib::Server svr;

    // 为每个接口创建独立的限流器（每秒最多2次请求）
    RateLimiter cpuLimiter(2);
    RateLimiter memLimiter(2);

    // /cpu 接口
    svr.Get("/cpu", [&](const httplib::Request&, httplib::Response& res) {
        if (!cpuLimiter.allow()) {
            res.status = 429;
            res.set_content("Too Many Requests", "text/plain");
            return;
        }
        float val;
        {
            std::lock_guard<std::mutex> lock(metrics.mtx);
            val = metrics.cpu_percent;
        }
        // 格式化保留一位小数
        char buffer[32];
        snprintf(buffer, sizeof(buffer), "%.1f", val);
        res.set_content(buffer, "text/plain");
    });

    // /mem 接口
    svr.Get("/mem", [&](const httplib::Request&, httplib::Response& res) {
        if (!memLimiter.allow()) {
            res.status = 429;
            res.set_content("Too Many Requests", "text/plain");
            return;
        }
        float val;
        {
            std::lock_guard<std::mutex> lock(metrics.mtx);
            val = metrics.mem_percent;
        }
        char buffer[32];
        snprintf(buffer, sizeof(buffer), "%.1f", val);
        res.set_content(buffer, "text/plain");
    });

    // 设置监听端口
    std::cout << "Server running on http://localhost:8080" << std::endl;
    svr.listen("0.0.0.0", 35008);

    // 停止后台线程
    running = false;
    updater.join();

    return 0;
}