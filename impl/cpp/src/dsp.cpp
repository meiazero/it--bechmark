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
    for (auto value : values) {
        for (double axis : {value.real(), value.imag()}) {
            const double scaled = axis * std::sqrt(10.0);
            output.push_back(scaled >= 0 ? 1 : 0);
            output.push_back(scaled >= -2 && scaled < 2 ? 1 : 0);
        }
    }
    return output;
}
int fft_index(int bin) { return (bin + FFT_SIZE) % FFT_SIZE; }

DspConfig::DspConfig(const Json& validated)
    : symbol_energy(validated["E_sym"]),
      awgn_channel(validated["channel"] == "awgn"),
      perfect_csi(validated["csi"] == "perfect"),
      stage_repetitions(validated["stages"]["repetitions"]) {
    const auto pilot_bins = validated["pilot_bins"].get<std::vector<int>>();
    for (int bin : pilot_bins) pilot_indices.push_back(fft_index(bin));
    pilot_values = validated["pilots"].get<std::vector<double>>();
    for (double power : validated["pdp"]) tap_scales.push_back(std::sqrt(power / 2));
    for (int bin : validated["data_bins"]) {
        data_indices.push_back(fft_index(bin));
        const auto right = std::upper_bound(pilot_bins.begin(), pilot_bins.end(), bin) - pilot_bins.begin();
        const auto left = right - 1;
        interpolation.push_back({static_cast<std::size_t>(left), static_cast<std::size_t>(right),
            double(bin - pilot_bins[left]) / (pilot_bins[right] - pilot_bins[left])});
    }
}

Values grid(const Values& data, const DspConfig& config) {
    Values spectrum(FFT_SIZE);
    for (std::size_t i = 0; i < data.size(); ++i) spectrum[config.data_indices[i]] = data[i];
    for (std::size_t i = 0; i < config.pilot_indices.size(); ++i)
        spectrum[config.pilot_indices[i]] = config.pilot_values[i];
    return spectrum;
}
Values extract(const Values& spectrum, const std::vector<int>& indices) {
    Values data(indices.size());
    for (std::size_t i = 0; i < indices.size(); ++i) data[i] = spectrum[indices[i]];
    return data;
}
Values transform(const Values& values, bool inverse) {
    itpp::cvec input(static_cast<int>(values.size()));
    for (int i = 0; i < input.size(); ++i) input[i] = values[i];
    // IT++ scales only the inverse by 1/N; both paths must be unitary.
    auto result = inverse ? itpp::ifft(input) : itpp::fft(input);
    double scale = inverse ? std::sqrt(values.size()) : 1 / std::sqrt(values.size());
    Values output(values.size());
    for (int i = 0; i < result.size(); ++i) output[i] = result[i] * scale;
    return output;
}
Values add_cp(const Values& values) {
    Values output(values.end() - CP_LENGTH, values.end());
    output.insert(output.end(), values.begin(), values.end());
    return output;
}
Values remove_cp(const Values& values) {
    return Values(values.begin() + CP_LENGTH, values.begin() + SAMPLES_WITH_CP);
}
Values convolve(const Values& values, const Values& taps) {
    // Retain the causal prefix; the discarded tail lies outside this symbol.
    Values output(values.size());
    // A tap-major traversal keeps samples contiguous without reordering each sum.
    for (std::size_t delay = 0; delay < taps.size() && delay < values.size(); ++delay) {
        for (std::size_t sample = delay; sample < values.size(); ++sample) {
            output[sample] += taps[delay] * values[sample - delay];
        }
    }
    return output;
}
Values response(const Values& taps) {
    // H[k] is the unscaled tap DFT, even though the signal transforms are unitary.
    Values output(FFT_SIZE);
    for (int bin = 0; bin < FFT_SIZE; ++bin) {
        for (std::size_t delay = 0; delay < taps.size(); ++delay) {
            const double phase = -2 * std::numbers::pi * bin * delay / FFT_SIZE;
            output[bin] += taps[delay] * std::exp(Complex(0, phase));
        }
    }
    return output;
}
std::pair<Values, Values> estimate(const Values& spectrum, const DspConfig& config) {
    auto pilot_estimates = extract(spectrum, config.pilot_indices);
    for (std::size_t i = 0; i < pilot_estimates.size(); ++i)
        pilot_estimates[i] /= config.pilot_values[i];
    Values data_estimates(config.data_indices.size());
    for (std::size_t i = 0; i < data_estimates.size(); ++i) {
        const auto [left, right, fraction] = config.interpolation[i];
        data_estimates[i] = pilot_estimates[left] + fraction * (pilot_estimates[right] - pilot_estimates[left]);
    }
    return {pilot_estimates, data_estimates};
}
std::pair<Values, U64> equalize(const Values& data, const Values& estimates) {
    Values output(data.size());
    U64 zeros = 0;
    for (std::size_t i = 0; i < data.size(); ++i) {
        if (estimates[i] == Complex(0)) {
            ++zeros;
        } else {
            output[i] = data[i] / estimates[i];
        }
    }
    return {output, zeros};
}
double noise_variance(double point, double symbol_energy) {
    double n0 = symbol_energy / (BITS_PER_OFDM_SYMBOL * std::pow(10.0, point / 10));
    if (!std::isfinite(n0) || n0 <= 0) throw std::invalid_argument("Eb/N0 exceeds the finite noise range");
    return n0;
}
Json golden(const std::string& id, const Json& in, const DspConfig& config) {
    if (id == "qam_map") return {{"symbols", encode(map_qam(in["bits"].get<Bits>()))}};
    if (id == "demap") return {{"bits", demap(decode(in["symbols"]))}};
    if (id == "grid") {
        auto spectrum = grid(decode(in["symbols"]), config);
        return {{"spectrum", encode(spectrum)}, {"data", encode(extract(spectrum, config.data_indices))},
                {"pilots", encode(extract(spectrum, config.pilot_indices))}};
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
        for (double point : in["ebn0_db"]) n0.push_back(noise_variance(point, config.symbol_energy));
        for (U64 seed : in["splitmix_inputs"]) sm.push_back(splitmix(seed));
        for (const auto& triple : in["batch_seed_inputs"]) batches.push_back(batch_seed(triple[0], triple[1], triple[2]));
        return {{"N0", n0}, {"splitmix_outputs", sm}, {"batch_seeds", batches}};
    }
    if (id != "end_to_end") throw std::runtime_error("Unknown golden case");
    auto original_bits = in["bits"].get<Bits>();
    auto taps = decode(in["taps"]);
    auto spectrum = grid(map_qam(original_bits), config);
    auto time = transform(spectrum, true);
    auto cp = add_cp(time);
    auto received = convolve(cp, taps);
    auto noise = decode(in["noise"]);
    for (std::size_t i = 0; i < received.size(); ++i) received[i] += noise[i];
    auto received_grid = transform(remove_cp(received), false);
    auto [pilots, estimates] = estimate(received_grid, config);
    auto data = extract(received_grid, config.data_indices);
    auto [equalized, zeros] = equalize(data, estimates);
    auto [perfect, ignored] = equalize(data, extract(response(taps), config.data_indices));
    auto bits = demap(equalized);
    U64 errors = 0;
    for (std::size_t i = 0; i < bits.size(); ++i) errors += bits[i] != original_bits[i];
    return {{"spectrum", encode(spectrum)}, {"time", encode(time)}, {"with_cp", encode(cp)},
            {"received", encode(received)}, {"received_fft", encode(received_grid)}, {"pilot_estimates", encode(pilots)},
            {"data_estimates", encode(estimates)}, {"equalized", encode(equalized)}, {"bits", bits},
            {"perfect_bits", demap(perfect)}, {"n_errors", errors}, {"zf_zero_count", zeros}};
}
void checked_add(U64& target, U64 value) {
    if (value > std::numeric_limits<U64>::max() - target) throw std::overflow_error("u64 counter overflow");
    target += value;
}
void Counts::add(const Counts& other) {
    checked_add(batches, other.batches);
    checked_add(errors, other.errors);
    checked_add(squares, other.squares);
    checked_add(symbols_with_errors, other.symbols_with_errors);
    checked_add(zeros, other.zeros);
}
Worker::Worker(const Json& validated) : config(validated) {
    transform(Values(FFT_SIZE), true);
    transform(Values(FFT_SIZE), false);
}
void Worker::seed(U64 value) {
    rng.seed(value);
    normal.reset();
}
Bits Worker::bits() {
    Bits output(BITS_PER_OFDM_SYMBOL);
    for (auto& bit : output) bit = int(rng() & 1);
    return output;
}
Values Worker::taps() {
    if (config.awgn_channel) return {Complex(1)};
    Values output(config.tap_scales.size());
    for (std::size_t i = 0; i < output.size(); ++i) {
        double real = normal(rng), imag = normal(rng);
        output[i] = Complex(real, imag) * config.tap_scales[i];
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
Counts Worker::decide(const Values& values, const Bits& original_bits) {
    auto recovered = demap(values);
    Counts counts;
    for (int i = 0; i < BITS_PER_OFDM_SYMBOL; ++i) counts.errors += recovered[i] != original_bits[i];
    counts.symbols_with_errors = counts.errors != 0;
    return counts;
}
Counts Worker::batch(U64 seed, double point) {
    this->seed(seed);
    Counts counts;
    const double n0 = noise_variance(point, config.symbol_energy);
    for (int symbol = 0; symbol < SYMBOLS_PER_BATCH; ++symbol) {
        const auto original_bits = bits();
        const auto channel_taps = taps();
        const auto transmit_grid = grid(map_qam(original_bits), config);
        const auto transmit_time = transform(transmit_grid, true);
        const auto prefixed = add_cp(transmit_time);
        const auto channel_output = convolve(prefixed, channel_taps);
        const auto received_time = remove_cp(awgn(channel_output, n0));
        const auto received_grid = transform(received_time, false);
        const auto estimates = config.perfect_csi
            ? extract(response(channel_taps), config.data_indices)
            : estimate(received_grid, config).second;
        const auto [equalized, zeros] = equalize(extract(received_grid, config.data_indices), estimates);
        auto symbol_counts = decide(equalized, original_bits);
        symbol_counts.zeros = zeros;
        counts.add(symbol_counts);
    }
    counts.batches = 1;
    counts.squares = counts.errors * counts.errors;
    return counts;
}
Json Worker::stages(U64 seed, double point) {
    this->seed(seed);
    std::vector<Bits> original_bits;
    std::vector<Values> qam_symbols, spectra, times, cps, channel_taps, received, noisy, stripped, transformed, estimates, equalized;
    double n0 = noise_variance(point, config.symbol_energy);
    for (int i = 0; i < SYMBOLS_PER_BATCH; ++i) {
        original_bits.push_back(bits());
        qam_symbols.push_back(map_qam(original_bits.back()));
        spectra.push_back(grid(qam_symbols.back(), config));
        times.push_back(transform(spectra.back(), true));
        cps.push_back(add_cp(times.back()));
        channel_taps.push_back(taps());
        received.push_back(convolve(cps.back(), channel_taps.back()));
        noisy.push_back(awgn(received.back(), n0));
        stripped.push_back(remove_cp(noisy.back()));
        transformed.push_back(transform(stripped.back(), false));
        estimates.push_back(estimate(transformed.back(), config).second);
        equalized.push_back(equalize(extract(transformed.back(), config.data_indices), estimates.back()).first);
    }
    Json output;
    // Observable sink prevents the compiler from deleting measured outputs.
    volatile double sink = 0;
    std::vector<std::pair<std::string, std::function<void(int)>>> stages = {
        {"bits", [&](int) { auto x = bits(); sink = x[0]; }},
        {"qam_map", [&](int i) { auto x = map_qam(original_bits[i]); sink = x[0].real(); }},
        {"grid", [&](int i) { auto x = grid(qam_symbols[i], config); sink = x[160].real(); }},
        {"ifft", [&](int i) { auto x = transform(spectra[i], true); sink = x[0].real(); }},
        {"cp_add", [&](int i) { auto x = add_cp(times[i]); sink = x[0].real(); }},
        {"channel_conv", [&](int i) { auto x = convolve(cps[i], channel_taps[i]); sink = x[0].real(); }},
        {"awgn", [&](int i) { auto x = awgn(received[i], n0); sink = x[0].real(); }},
        {"cp_remove", [&](int i) { auto x = remove_cp(noisy[i]); sink = x[0].real(); }},
        {"fft", [&](int i) { auto x = transform(stripped[i], false); sink = x[0].real(); }},
        {"chan_est", [&](int i) { auto x = estimate(transformed[i], config); sink = x.second[0].real(); }},
        {"zf", [&](int i) { auto x = equalize(extract(transformed[i], config.data_indices), estimates[i]); sink = x.first[0].real(); }},
        {"demap_count", [&](int i) { auto x = decide(equalized[i], original_bits[i]); sink = double(x.errors); }}
    };
    U64 repetitions = config.stage_repetitions;
    for (const auto& [name, action] : stages) {
        std::vector<double> samples;
        for (U64 r = 0; r < repetitions; ++r) {
            auto start = std::chrono::steady_clock::now();
            for (int i = 0; i < SYMBOLS_PER_BATCH; ++i) action(i);
            samples.push_back(std::chrono::duration<double, std::nano>(std::chrono::steady_clock::now()-start).count() / SYMBOLS_PER_BATCH);
        }
        std::sort(samples.begin(), samples.end());
        output[name] = (samples[(samples.size()-1)/2] + samples[samples.size()/2]) / 2;
    }
    std::vector<double> samples;
    for (U64 r = 0; r < repetitions; ++r) {
        auto start = std::chrono::steady_clock::now();
        auto counts = batch(batch_seed(seed, 0, r), point); sink = double(counts.errors);
        samples.push_back(std::chrono::duration<double, std::nano>(std::chrono::steady_clock::now()-start).count() / SYMBOLS_PER_BATCH);
    }
    std::sort(samples.begin(), samples.end());
    output["e2e"] = (samples[(samples.size()-1)/2] + samples[samples.size()/2]) / 2;
    (void)sink;
    return output;
}
