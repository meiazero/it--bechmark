#pragma once

#include <itpp/itbase.h>
#include <itpp/itsignal.h>
#include <nlohmann/json.hpp>
#include <complex>
#include <cstddef>
#include <cstdint>
#include <random>
#include <vector>

using Json = nlohmann::json;
using Complex = std::complex<double>;
using Values = std::vector<Complex>;
using Bits = std::vector<int>;
using U64 = std::uint64_t;

inline constexpr int FFT_SIZE = 256;
inline constexpr int CP_LENGTH = 32;
inline constexpr int SAMPLES_WITH_CP = FFT_SIZE + CP_LENGTH;
inline constexpr int SYMBOLS_PER_BATCH = 256;
inline constexpr int BITS_PER_OFDM_SYMBOL = 672;
inline constexpr U64 BITS_PER_BATCH = SYMBOLS_PER_BATCH * BITS_PER_OFDM_SYMBOL;

// Physical bin coordinates determine interpolation; FFT storage indices wrap at DC.
struct Interpolation {
    std::size_t left;
    std::size_t right;
    double fraction;
};
struct DspConfig {
    std::vector<int> data_indices, pilot_indices;
    std::vector<double> pilot_values, tap_scales;
    std::vector<Interpolation> interpolation;
    double symbol_energy;
    bool awgn_channel, perfect_csi;
    U64 stage_repetitions;
    explicit DspConfig(const Json& validated);
};

U64 splitmix(U64 seed);
U64 batch_seed(U64 master, U64 point, U64 batch);
Values decode(const Json& input);
Json encode(const Values& input);
Values map_qam(const Bits& bits);
Bits demap(const Values& values);
Values grid(const Values& data, const DspConfig& config);
Values extract(const Values& values, const std::vector<int>& indices);
Values transform(const Values& values, bool inverse);
Values add_cp(const Values& values);
Values remove_cp(const Values& values);
Values convolve(const Values& values, const Values& taps);
Values response(const Values& taps);
std::pair<Values, Values> estimate(const Values& spectrum, const DspConfig& config);
std::pair<Values, U64> equalize(const Values& data, const Values& estimates);
double noise_variance(double point, double symbol_energy);
Json golden(const std::string& id, const Json& input, const DspConfig& config);

struct Counts {
    U64 batches = 0;
    U64 errors = 0;
    U64 squares = 0;
    U64 symbols_with_errors = 0;
    U64 zeros = 0;
    void add(const Counts& other);
};

// ponytail: symbol-sized buffers keep the first implementation readable;
// the single M8 profiler round may replace measured allocation hotspots.
struct Worker {
    const DspConfig config;
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
