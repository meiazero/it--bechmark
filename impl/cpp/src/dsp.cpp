#include "dsp.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <functional>
#include <limits>
#include <numbers>
#include <stdexcept>

U64 splitmix(U64 x) {
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31);
}
U64 batch_seed(U64 master, U64 point, U64 batch) {
    return splitmix(splitmix(splitmix(master) ^ point) ^ batch);
}
Values decode(const Json& input) {
    Values values;
    for (const auto& x : input) values.emplace_back(x.at(0).get<double>(), x.at(1).get<double>());
    return values;
}
Json encode(const Values& input) {
    Json output = Json::array();
    for (auto x : input) output.push_back({x.real(), x.imag()});
    return output;
}
Values map_qam(const Bits& bits) {
    constexpr int levels[] = {-3, -1, 3, 1};
    Values output(bits.size() / 4);
    for (std::size_t i = 0; i < output.size(); ++i)
        output[i] = Complex(levels[2 * bits[4*i] + bits[4*i+1]],
                            levels[2 * bits[4*i+2] + bits[4*i+3]]) / std::sqrt(10.0);
    return output;
}
Bits demap(const Values& values) {
    Bits output;
    output.reserve(values.size() * 4);
    for (auto value : values) for (double axis : {value.real(), value.imag()}) {
        double scaled = axis * std::sqrt(10.0);
        output.push_back(scaled >= 0 ? 1 : 0);
        output.push_back(scaled >= -2 && scaled < 2 ? 1 : 0);
    }
    return output;
}
int index(int bin) { return (bin + 256) % 256; }
Values grid(const Values& data, const Json& config) {
    Values output(256);
    for (std::size_t i = 0; i < data.size(); ++i) output[index(config["data_bins"][i])] = data[i];
    for (std::size_t i = 0; i < 24; ++i) output[index(config["pilot_bins"][i])] = config["pilots"][i].get<double>();
    return output;
}
Values extract(const Values& values, const Json& bins) {
    Values output;
    for (int bin : bins) output.push_back(values[index(bin)]);
    return output;
}
Values transform(const Values& values, bool inverse) {
    itpp::cvec input(static_cast<int>(values.size()));
    for (int i = 0; i < input.size(); ++i) input[i] = values[i];
    auto result = inverse ? itpp::ifft(input) : itpp::fft(input);
    double scale = inverse ? std::sqrt(values.size()) : 1 / std::sqrt(values.size());
    Values output(values.size());
    for (int i = 0; i < result.size(); ++i) output[i] = result[i] * scale;
    return output;
}
Values add_cp(const Values& values) {
    Values output(values.end() - 32, values.end());
    output.insert(output.end(), values.begin(), values.end());
    return output;
}
Values remove_cp(const Values& values) { return Values(values.begin()+32, values.begin()+288); }
Values convolve(const Values& values, const Values& taps) {
    Values output(values.size());
    for (std::size_t n = 0; n < values.size(); ++n)
        for (std::size_t l = 0; l < taps.size() && l <= n; ++l) output[n] += taps[l] * values[n-l];
    return output;
}
Values response(const Values& taps) {
    Values output(256);
    for (int k = 0; k < 256; ++k) for (std::size_t l = 0; l < taps.size(); ++l)
        output[k] += taps[l] * std::exp(Complex(0, -2 * std::numbers::pi * k * l / 256));
    return output;
}
std::pair<Values, Values> estimate(const Values& spectrum, const Json& config) {
    auto pilots = extract(spectrum, config["pilot_bins"]);
    for (std::size_t i = 0; i < pilots.size(); ++i) pilots[i] /= config["pilots"][i].get<double>();
    auto bins = config["pilot_bins"].get<std::vector<int>>();
    Values estimates;
    for (int k : config["data_bins"]) {
        auto right = std::upper_bound(bins.begin(), bins.end(), k) - bins.begin();
        auto left = right - 1;
        double fraction = double(k - bins[left]) / (bins[right] - bins[left]);
        estimates.push_back(pilots[left] + fraction * (pilots[right] - pilots[left]));
    }
    return {pilots, estimates};
}
std::pair<Values, U64> equalize(const Values& data, const Values& estimates) {
    Values output(data.size());
    U64 zeros = 0;
    for (std::size_t i = 0; i < data.size(); ++i) {
        if (estimates[i] == Complex(0)) ++zeros;
        else output[i] = data[i] / estimates[i];
    }
    return {output, zeros};
}
double noise_variance(double point, const Json& config) {
    double n0 = config["E_sym"].get<double>() / (672 * std::pow(10.0, point / 10));
    if (!std::isfinite(n0) || n0 <= 0) throw std::invalid_argument("Eb/N0 exceeds the finite noise range");
    return n0;
}
Json golden(const std::string& id, const Json& in, const Json& config) {
    if (id == "qam_map") return {{"symbols", encode(map_qam(in["bits"].get<Bits>()))}};
    if (id == "demap") return {{"bits", demap(decode(in["symbols"]))}};
    if (id == "grid") {
        auto spectrum = grid(decode(in["symbols"]), config);
        return {{"spectrum", encode(spectrum)}, {"data", encode(extract(spectrum, config["data_bins"]))},
                {"pilots", encode(extract(spectrum, config["pilot_bins"]))}};
    }
    if (id == "transforms" || id == "fft_impulse") {
        auto values = decode(in["values"]);
        return {{"fft", encode(transform(values, false))}, {"ifft", encode(transform(values, true))}};
    }
    if (id == "cp") {
        auto cp = add_cp(decode(in["values"]));
        return {{"with_cp", encode(cp)}, {"without_cp", encode(remove_cp(cp))}};
    }
    if (id == "channel") return {{"convolved", encode(convolve(decode(in["values"]), decode(in["taps"])))},
                                 {"response", encode(response(decode(in["taps"])))}};
    if (id == "estimation") {
        auto [pilots, estimates] = estimate(decode(in["spectrum"]), config);
        return {{"pilot_estimates", encode(pilots)}, {"data_estimates", encode(estimates)}};
    }
    if (id == "zf") {
        auto [values, zeros] = equalize(decode(in["data"]), decode(in["estimates"]));
        return {{"equalized", encode(values)}, {"zf_zero_count", zeros}};
    }
    if (id == "noise_seed") {
        Json n0 = Json::array(), sm = Json::array(), batches = Json::array();
        for (double point : in["ebn0_db"]) n0.push_back(noise_variance(point, config));
        for (U64 seed : in["splitmix_inputs"]) sm.push_back(splitmix(seed));
        for (const auto& triple : in["batch_seed_inputs"]) batches.push_back(batch_seed(triple[0], triple[1], triple[2]));
        return {{"N0", n0}, {"splitmix_outputs", sm}, {"batch_seeds", batches}};
    }
    if (id != "end_to_end") throw std::runtime_error("Unknown golden case");
    auto original = in["bits"].get<Bits>();
    auto taps = decode(in["taps"]);
    auto spectrum = grid(map_qam(original), config);
    auto time = transform(spectrum, true);
    auto cp = add_cp(time);
    auto received = convolve(cp, taps);
    auto noise = decode(in["noise"]);
    for (std::size_t i = 0; i < received.size(); ++i) received[i] += noise[i];
    auto rx = transform(remove_cp(received), false);
    auto [pilots, estimates] = estimate(rx, config);
    auto data = extract(rx, config["data_bins"]);
    auto [eq, zeros] = equalize(data, estimates);
    auto [perfect, ignored] = equalize(data, extract(response(taps), config["data_bins"]));
    auto bits = demap(eq);
    U64 errors = 0;
    for (std::size_t i = 0; i < bits.size(); ++i) errors += bits[i] != original[i];
    return {{"spectrum", encode(spectrum)}, {"time", encode(time)}, {"with_cp", encode(cp)},
            {"received", encode(received)}, {"received_fft", encode(rx)}, {"pilot_estimates", encode(pilots)},
            {"data_estimates", encode(estimates)}, {"equalized", encode(eq)}, {"bits", bits},
            {"perfect_bits", demap(perfect)}, {"n_errors", errors}, {"zf_zero_count", zeros}};
}
void checked_add(U64& target, U64 value) {
    if (value > std::numeric_limits<U64>::max() - target) throw std::overflow_error("u64 counter overflow");
    target += value;
}
void Counts::add(const Counts& other) {
    checked_add(batches, other.batches); checked_add(errors, other.errors);
    checked_add(squares, other.squares); checked_add(symbols_with_errors, other.symbols_with_errors);
    checked_add(zeros, other.zeros);
}
Worker::Worker(const Json& config) : config(config) {
    transform(Values(256), true); transform(Values(256), false);
}
void Worker::seed(U64 value) { rng.seed(value); normal.reset(); }
Bits Worker::bits() {
    Bits output(672);
    for (auto& bit : output) bit = int(rng() & 1);
    return output;
}
Values Worker::taps() {
    if (config["channel"] == "awgn") return {Complex(1)};
    Values output(8);
    for (int i = 0; i < 8; ++i) {
        double real = normal(rng), imag = normal(rng);
        output[i] = Complex(real, imag) * std::sqrt(config["pdp"][i].get<double>() / 2);
    }
    return output;
}
Values Worker::awgn(const Values& received, double n0) {
    Values output = received;
    double scale = std::sqrt(n0 / 2);
    for (auto& value : output) {
        double real = normal(rng), imag = normal(rng);
        value += Complex(real, imag) * scale;
    }
    return output;
}
Counts Worker::decide(const Values& values, const Bits& original) {
    auto recovered = demap(values);
    Counts counts;
    for (int i = 0; i < 672; ++i) counts.errors += recovered[i] != original[i];
    counts.symbols_with_errors = counts.errors != 0;
    return counts;
}
Counts Worker::batch(U64 seed, double point) {
    this->seed(seed);
    Counts counts;
    double n0 = noise_variance(point, config);
    for (int symbol = 0; symbol < 256; ++symbol) {
        auto original = bits();
        auto h = taps();
        auto cp = add_cp(transform(grid(map_qam(original), config), true));
        auto rx = transform(remove_cp(awgn(convolve(cp, h), n0)), false);
        auto estimates = config["csi"] == "perfect" ? extract(response(h), config["data_bins"])
                                                   : estimate(rx, config).second;
        auto [eq, zeros] = equalize(extract(rx, config["data_bins"]), estimates);
        auto result = decide(eq, original);
        result.zeros = zeros;
        counts.add(result);
    }
    counts.batches = 1; counts.squares = counts.errors * counts.errors;
    return counts;
}
Json Worker::stages(U64 seed, double point) {
    this->seed(seed);
    std::vector<Bits> originals;
    std::vector<Values> qam, spectra, times, cps, hs, received, noisy, stripped, transformed, estimates, eq;
    double n0 = noise_variance(point, config);
    for (int i = 0; i < 256; ++i) {
        originals.push_back(bits()); qam.push_back(map_qam(originals.back()));
        spectra.push_back(grid(qam.back(), config)); times.push_back(transform(spectra.back(), true));
        cps.push_back(add_cp(times.back())); hs.push_back(taps());
        received.push_back(convolve(cps.back(), hs.back())); noisy.push_back(awgn(received.back(), n0));
        stripped.push_back(remove_cp(noisy.back())); transformed.push_back(transform(stripped.back(), false));
        estimates.push_back(estimate(transformed.back(), config).second);
        eq.push_back(equalize(extract(transformed.back(), config["data_bins"]), estimates.back()).first);
    }
    Json output;
    // Observable sink prevents the compiler from deleting measured outputs.
    volatile double sink = 0;
    std::vector<std::pair<std::string, std::function<void(int)>>> stages = {
        {"bits", [&](int) { auto x = bits(); sink = x[0]; }},
        {"qam_map", [&](int i) { auto x = map_qam(originals[i]); sink = x[0].real(); }},
        {"grid", [&](int i) { auto x = grid(qam[i], config); sink = x[160].real(); }},
        {"ifft", [&](int i) { auto x = transform(spectra[i], true); sink = x[0].real(); }},
        {"cp_add", [&](int i) { auto x = add_cp(times[i]); sink = x[0].real(); }},
        {"channel_conv", [&](int i) { auto h = taps(); auto x = convolve(cps[i], h); sink = x[0].real(); }},
        {"awgn", [&](int i) { auto x = awgn(received[i], n0); sink = x[0].real(); }},
        {"cp_remove", [&](int i) { auto x = remove_cp(noisy[i]); sink = x[0].real(); }},
        {"fft", [&](int i) { auto x = transform(stripped[i], false); sink = x[0].real(); }},
        {"chan_est", [&](int i) { auto x = estimate(transformed[i], config); sink = x.second[0].real(); }},
        {"zf", [&](int i) { auto x = equalize(extract(transformed[i], config["data_bins"]), estimates[i]); sink = x.first[0].real(); }},
        {"demap_count", [&](int i) { auto x = decide(eq[i], originals[i]); sink = double(x.errors); }}
    };
    U64 repetitions = config["stages"]["repetitions"];
    for (const auto& [name, action] : stages) {
        std::vector<double> samples;
        for (U64 r = 0; r < repetitions; ++r) {
            auto start = std::chrono::steady_clock::now();
            for (int i = 0; i < 256; ++i) action(i);
            samples.push_back(std::chrono::duration<double, std::nano>(std::chrono::steady_clock::now()-start).count() / 256);
        }
        std::sort(samples.begin(), samples.end());
        output[name] = (samples[(samples.size()-1)/2] + samples[samples.size()/2]) / 2;
    }
    std::vector<double> samples;
    for (U64 r = 0; r < repetitions; ++r) {
        auto start = std::chrono::steady_clock::now();
        auto counts = batch(batch_seed(seed, 0, r), point); sink = double(counts.errors);
        samples.push_back(std::chrono::duration<double, std::nano>(std::chrono::steady_clock::now()-start).count() / 256);
    }
    std::sort(samples.begin(), samples.end());
    output["e2e"] = (samples[(samples.size()-1)/2] + samples[samples.size()/2]) / 2;
    (void)sink;
    return output;
}
