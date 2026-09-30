#pragma once

#include <itpp/itbase.h>
#include <itpp/itsignal.h>
#include <nlohmann/json.hpp>
#include <array>
#include <complex>
#include <cstdint>
#include <random>
#include <vector>

using Json = nlohmann::json;
using Complex = std::complex<double>;
using Values = std::vector<Complex>;
using Bits = std::vector<int>;
using U64 = std::uint64_t;

U64 splitmix(U64 seed);
U64 batch_seed(U64 master, U64 point, U64 batch);
Values decode(const Json& input);
Json encode(const Values& input);
Values map_qam(const Bits& bits);
Bits demap(const Values& values);
Values grid(const Values& data, const Json& config);
Values extract(const Values& values, const Json& bins);
Values transform(const Values& values, bool inverse);
Values add_cp(const Values& values);
Values remove_cp(const Values& values);
Values convolve(const Values& values, const Values& taps);
Values response(const Values& taps);
std::pair<Values, Values> estimate(const Values& spectrum, const Json& config);
std::pair<Values, U64> equalize(const Values& data, const Values& estimates);
double noise_variance(double point, const Json& config);
Json golden(const std::string& id, const Json& input, const Json& config);

struct Counts {
    U64 batches = 0, errors = 0, squares = 0, symbols_with_errors = 0, zeros = 0;
    void add(const Counts& other);
};

// ponytail: symbol-sized buffers keep the first implementation readable;
// the single M8 profiler round may replace measured allocation hotspots.
struct Worker {
    const Json& config;
    std::mt19937_64 rng;
    std::normal_distribution<double> normal;
    explicit Worker(const Json& config);
    void seed(U64 value);
    Bits bits();
    Values taps();
    Values awgn(const Values& received, double n0);
    Counts decide(const Values& values, const Bits& original);
    Counts batch(U64 seed, double point);
    Json stages(U64 seed, double point);
};
