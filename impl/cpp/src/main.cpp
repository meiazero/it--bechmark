#include "dsp.hpp"
#include <atomic>
#include <charconv>
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <set>
#include <sstream>
#include <thread>
#include <sys/wait.h>
#include <unistd.h>

namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
const fs::path root = fs::weakly_canonical(PROJECT_ROOT);
constexpr U64 batch_bits = BITS_PER_BATCH;

std::string read(const fs::path& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw std::invalid_argument("Cannot read " + path.string());
    std::ostringstream text;
    text << file.rdbuf();
    if (file.bad()) throw std::invalid_argument("Failed reading " + path.string());
    return text.str();
}
Json parse(const std::string& text) {
    std::vector<std::set<std::string>> keys;
    auto callback = [&](int, Json::parse_event_t event, Json& value) {
        if (event == Json::parse_event_t::object_start) keys.emplace_back();
        else if (event == Json::parse_event_t::key) {
            if (!keys.back().insert(value.get<std::string>()).second)
                throw std::invalid_argument("Duplicate JSON key");
        } else if (event == Json::parse_event_t::object_end) keys.pop_back();
        return true;
    };
    try { return Json::parse(text, callback); }
    catch (const Json::exception& e) { throw std::invalid_argument(e.what()); }
}
void object_keys(const Json& value, const Json& reference) {
    if (!value.is_object() || value.size() != reference.size()) throw std::invalid_argument("Object keys differ");
    for (auto it = reference.begin(); it != reference.end(); ++it)
        if (!value.contains(it.key())) throw std::invalid_argument("Missing key: " + it.key());
}
U64 integer(const Json& value, const std::string& name, U64 minimum = 1,
            U64 maximum = std::numeric_limits<U64>::max()) {
    if (!value.is_number_unsigned() || value.get<U64>() < minimum || value.get<U64>() > maximum)
        throw std::invalid_argument(name + " must be a u64 in the permitted range");
    return value.get<U64>();
}
double number(const Json& value) {
    if (!value.is_number() || !std::isfinite(value.get<double>())) throw std::invalid_argument("Expected finite number");
    return value.get<double>();
}
void validate(const Json& config, const std::string& mode) {
    auto profile = parse(read(root / "contract/profile_main.json"));
    object_keys(config, profile);
    for (const std::string name : {"schema_version", "profile_id", "N_fft", "N_cp", "M", "active_bins",
              "pilot_bins", "data_bins", "pilots", "pdp", "E_sym", "bits_per_symbol", "B", "warmup_batches"})
        if (config.at(name).dump() != profile.at(name).dump()) throw std::invalid_argument(name + " differs from frozen profile");
    integer(config["master_seed"], "master_seed", 0);
    if (config["channel"] != "rayleigh" && config["channel"] != "awgn") throw std::invalid_argument("Unknown channel");
    if (config["csi"] != "estimated" && config["csi"] != "perfect") throw std::invalid_argument("Unknown CSI");
    const auto& ber = config["ber"];
    object_keys(ber, profile["ber"]);
    integer(ber["target_errors"], "target_errors");
    U64 min = integer(ber["min_batches"], "min_batches");
    U64 max = integer(ber["max_bits"], "max_bits", 1, std::numeric_limits<U64>::max() - batch_bits + 1);
    if (min > max / batch_bits) throw std::invalid_argument("max_bits below minimum batch payload");
    if (!ber["ebn0_db"].is_array() || ber["ebn0_db"].empty()) throw std::invalid_argument("Empty Eb/N0 points");
    for (const auto& point : ber["ebn0_db"]) noise_variance(number(point), config["E_sym"].get<double>());
    object_keys(config["perf"], profile["perf"]);
    if (!config["perf"]["ebn0_db"].is_number_unsigned() || config["perf"]["ebn0_db"] != 10)
        throw std::invalid_argument("perf Eb/N0 must be integer 10");
    if (config["perf"]["n_batches"].is_null()) {
        if (mode == "perf") throw std::invalid_argument("perf.n_batches awaits M8 calibration");
    } else integer(config["perf"]["n_batches"], "perf.n_batches", 1, std::numeric_limits<U64>::max() / batch_bits);
    object_keys(config["stages"], profile["stages"]);
    integer(config["stages"]["repetitions"], "stages.repetitions");
    if ((mode == "perf" || mode == "stages") && config["csi"] != "estimated") throw std::invalid_argument("Perfect CSI is diagnostic only");
}
U64 cli_integer(const std::string& value) {
    U64 result;
    auto [end, error] = std::from_chars(value.data(), value.data()+value.size(), result);
    if (error != std::errc() || end != value.data()+value.size() || result == 0) throw std::invalid_argument("workers must be a positive u64");
    return result;
}
// Metadata uses native utilities, before any worker exists, and hashes the bytes
// already parsed. No shell interpolates paths or input text.
std::string capture(std::vector<std::string> arguments, const std::string& input = "") {
    int in[2], out[2];
    if (pipe(in) || pipe(out)) throw std::runtime_error("Cannot create metadata pipes");
    pid_t pid = fork();
    if (pid == -1) throw std::runtime_error("Cannot spawn metadata utility");
    if (pid == 0) {
        dup2(in[0], STDIN_FILENO); dup2(out[1], STDOUT_FILENO);
        close(in[0]); close(in[1]); close(out[0]); close(out[1]);
        std::vector<char*> argv;
        for (auto& arg : arguments) argv.push_back(arg.data());
        argv.push_back(nullptr); execvp(argv[0], argv.data()); _exit(127);
    }
    close(in[0]); close(out[1]);
    std::size_t written = 0;
    while (written < input.size()) {
        auto count = write(in[1], input.data()+written, input.size()-written);
        if (count <= 0) throw std::runtime_error("Metadata input failed");
        written += count;
    }
    close(in[1]);
    std::string output; char buffer[4096]; ssize_t count;
    while ((count = ::read(out[0], buffer, sizeof buffer)) > 0) output.append(buffer, count);
    close(out[0]); int status;
    if (waitpid(pid, &status, 0) < 0 || !WIFEXITED(status) || WEXITSTATUS(status)) throw std::runtime_error("Metadata utility failed");
    return output.substr(0, output.find_first_of(" \r\n"));
}

class Pool {
    const Json& config;
    std::mutex mutex;
    std::condition_variable changed, done;
    std::vector<std::thread> threads;
    std::vector<std::unique_ptr<Worker>> workers;
    std::vector<Counts> results;
    std::exception_ptr failure;
    std::atomic<U64> next{0};
    U64 begin = 0, end = 0, point = 0, master = 0, epoch = 0;
    double db = 0;
    std::size_t ready = 0, finished = 0;
    bool stopping = false;
    void work(std::size_t id) {
        std::unique_lock lock(mutex);
        try { workers[id] = std::make_unique<Worker>(config); }
        catch (...) { failure = std::current_exception(); }
        ++ready; done.notify_one();
        U64 previous = 0;
        for (;;) {
            changed.wait(lock, [&] { return stopping || epoch != previous; });
            if (stopping) return;
            previous = epoch; lock.unlock();
            try {
                U64 index;
                while ((index = next.fetch_add(1)) < end)
                    results[index-begin] = workers[id]->batch(batch_seed(master, point, index), db);
            } catch (...) { std::lock_guard guard(mutex); failure = std::current_exception(); }
            lock.lock(); ++finished; done.notify_one();
        }
    }
public:
    Pool(const Json& config, std::size_t n) : config(config), workers(n) {
        try { for (std::size_t i = 0; i < n; ++i) threads.emplace_back([&, i] { work(i); }); }
        catch (...) { shutdown(); throw; }
        std::unique_lock lock(mutex);
        done.wait(lock, [&] { return ready == n; });
        if (failure) { lock.unlock(); shutdown(); std::rethrow_exception(failure); }
    }
    void shutdown() {
        { std::lock_guard lock(mutex); stopping = true; }
        changed.notify_all();
        for (auto& thread : threads) if (thread.joinable()) thread.join();
    }
    ~Pool() { shutdown(); }
    std::vector<Counts> run(U64 seed, U64 point_index, U64 first, U64 last, double ebn0) {
        std::unique_lock lock(mutex);
        begin = first; end = last; next = first; master = seed; point = point_index; db = ebn0;
        results.assign(last-first, Counts{}); finished = 0; ++epoch;
        changed.notify_all();
        done.wait(lock, [&] { return finished == threads.size(); });
        if (failure) std::rethrow_exception(failure);
        return std::move(results);
    }
};
double seconds(Clock::time_point start) { return std::chrono::duration<double>(Clock::now()-start).count(); }

int main(int argc, char** argv) {
    auto setup_start = Clock::now();
    std::string mode, config_path, out_path;
    U64 workers = 0;
    Json config;
    std::string config_bytes;
    try {
        if (argc != 9) throw std::invalid_argument("Usage: ofdm --config FILE --mode MODE --workers P --out FILE");
        std::set<std::string> seen;
        for (int i = 1; i < argc; i += 2) {
            std::string key = argv[i], value = argv[i+1];
            if (!seen.insert(key).second) throw std::invalid_argument("Duplicate CLI option");
            if (key == "--config") config_path = value;
            else if (key == "--out") out_path = value;
            else if (key == "--mode") mode = value;
            else if (key == "--workers") workers = cli_integer(value);
            else throw std::invalid_argument("Unknown CLI option");
        }
        if (config_path.empty() || out_path.empty() || workers == 0 ||
            (mode != "golden" && mode != "ber" && mode != "perf" && mode != "stages")) throw std::invalid_argument("Missing or invalid CLI option");
        config_bytes = read(config_path);
        config = parse(config_bytes);
        validate(config, mode);
    } catch (const std::exception& e) { std::cerr << "Invalid configuration: " << e.what() << '\n'; return 2; }
    try {
        Json base = {{"schema_version", 1}, {"impl", "cpp"}, {"mode", mode},
            {"git_sha", capture({"git", "-C", root.string(), "rev-parse", "HEAD"})},
            {"profile_id", config["profile_id"]}, {"master_seed", config["master_seed"]},
            {"config_sha256", capture({"sha256sum"}, config_bytes)}, {"workers", workers}};
        std::vector<Json> records;
        if (mode == "golden") {
            const DspConfig dsp_config(config);
            for (const auto& file : fs::directory_iterator(root / "contract/golden")) {
                if (file.path().extension() != ".json") continue;
                auto vector = parse(read(file.path()));
                auto record = base;
                record["case_id"] = vector["case_id"];
                record["outputs"] = golden(vector["case_id"], vector["inputs"], dsp_config);
                records.push_back(record);
            }
        } else {
            Pool pool(config, workers);
            std::unique_ptr<Worker> stage_worker;
            if (mode == "stages") stage_worker = std::make_unique<Worker>(config);
            double setup_s = seconds(setup_start);
            auto warm_start = Clock::now();
            U64 seed = config["master_seed"];
            pool.run(splitmix(seed ^ 0x7761726d7570ULL), 0, 0, 4, 10);
            double warmup_s = seconds(warm_start);
            Json points = mode == "ber" ? config["ber"]["ebn0_db"] : Json::array({10});
            for (std::size_t p = 0; p < points.size(); ++p) {
                double point = points[p];
                Counts counts;
                U64 limit = mode == "ber" ? (config["ber"]["max_bits"].get<U64>() + batch_bits - 1) / batch_bits
                          : mode == "perf" ? config["perf"]["n_batches"].get<U64>() : 1;
                auto work_start = Clock::now();
                std::string status = mode == "ber" ? "max_bits" : "fixed_work";
                for (U64 first = 0; first < limit;) {
                    U64 last = first + std::min<U64>(limit-first, std::max<U64>(workers * 2, 4));
                    auto results = pool.run(seed, p, first, last, point);
                    bool stop = false;
                    for (const auto& result : results) {
                        counts.add(result);
                        if (mode == "ber" && counts.batches >= config["ber"]["min_batches"].get<U64>() &&
                            counts.errors >= config["ber"]["target_errors"].get<U64>()) {
                            status = "target_errors";
                            stop = true;
                            break;
                        }
                        if (mode == "ber" && counts.batches * batch_bits >= config["ber"]["max_bits"].get<U64>()) {
                            stop = true;
                            break;
                        }
                    }
                    if (stop) break;
                    first = last;
                }
                Json timings;
                if (mode == "stages") timings = stage_worker->stages(batch_seed(seed, p, 0), point);
                double work_s = seconds(work_start);
                auto record = base;
                record.update({{"ebn0_db", point}, {"n_batches", counts.batches}, {"n_symbols", counts.batches * SYMBOLS_PER_BATCH},
                    {"n_bits", counts.batches * batch_bits}, {"n_errors", counts.errors}, {"sum_batch_errors_sq", counts.squares},
                    {"n_symbols_with_errors", counts.symbols_with_errors}, {"zf_zero_count", counts.zeros}, {"status", status},
                    {"setup_s", setup_s}, {"warmup_s", warmup_s}, {"work_s", work_s}});
                if (mode == "stages") record["stage_ns_per_symbol"] = timings;
                records.push_back(record);
            }
        }
        auto temporary = out_path + ".tmp." + std::to_string(getpid());
        std::ofstream file(temporary);
        if (!file) throw std::runtime_error("Cannot create output");
        for (const auto& record : records) file << record.dump() << '\n';
        file.close();
        if (!file) throw std::runtime_error("Failed writing output");
        fs::rename(temporary, out_path);
        return 0;
    } catch (const std::exception& e) { std::cerr << "Execution failed: " << e.what() << '\n'; return 1; }
}
