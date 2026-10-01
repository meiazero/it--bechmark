#include <itpp/itbase.h>
#include <itpp/itsignal.h>
#include <fftw3.h>
#include <dlfcn.h>

#include <algorithm>
#include <array>
#include <barrier>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <thread>
#include <vector>

namespace {
unsigned forward_flags = std::numeric_limits<unsigned>::max();
unsigned backward_flags = std::numeric_limits<unsigned>::max();
unsigned forward_plans = 0;
unsigned backward_plans = 0;
constexpr unsigned seed = 4257;
constexpr unsigned reseed = 9182;
constexpr int sample_count = 64;

itpp::cvec draw() {
    const itpp::bvec bits = itpp::randb(16);
    const itpp::vec normals = itpp::randn(16);
    const itpp::cvec complex_normals = itpp::randn_c(16);
    itpp::cvec result(48);
    for (int index = 0; index < 16; ++index) {
        result[index] = static_cast<int>(bits[index]);
        result[index + 16] = normals[index];
        result[index + 32] = complex_normals[index];
    }
    return result;
}

std::vector<itpp::cvec> serial_samples(bool reset_halfway) {
    itpp::RNG_reset(seed);
    std::vector<itpp::cvec> samples;
    for (int index = 0; index < sample_count; ++index) {
        if (reset_halfway && index == sample_count / 2) {
            itpp::RNG_reset(reseed);
        }
        samples.push_back(draw());
    }
    return samples;
}

bool matches(const std::vector<itpp::cvec>& actual,
             const std::vector<itpp::cvec>& expected, int begin, int end) {
    for (int index = begin; index < end; ++index) {
        for (int entry = 0; entry < actual[index].size(); ++entry) {
            if (actual[index][entry] != expected[index][entry]) {
                return false;
            }
        }
    }
    return true;
}
}  // namespace

// Interposition observes the installed IT++ binary rather than assuming its build flags.
extern "C" fftw_plan fftw_plan_dft_1d(int size, fftw_complex* input,
                                     fftw_complex* output, int sign, unsigned flags) {
    using Planner = fftw_plan (*)(int, fftw_complex*, fftw_complex*, int, unsigned);
    const auto planner = reinterpret_cast<Planner>(dlsym(RTLD_NEXT, "fftw_plan_dft_1d"));
    if (planner == nullptr) {
        std::cerr << "Cannot resolve the FFTW planner\n";
        std::exit(1);
    }
    if (size == 256) {
        (sign == FFTW_FORWARD ? forward_flags : backward_flags) = flags;
        ++(sign == FFTW_FORWARD ? forward_plans : backward_plans);
    }
    return planner(size, input, output, sign, flags);
}

int main() {
    itpp::cvec impulse(256);
    impulse.zeros();
    impulse[0] = 1.0;
    const itpp::cvec spectrum = itpp::fft(impulse);
    const itpp::cvec recovered = itpp::ifft(spectrum);
    double scaling_error = 0.0;
    for (int index = 0; index < 256; ++index) {
        scaling_error = std::max(scaling_error, std::abs(spectrum[index] - 1.0));
        scaling_error = std::max(scaling_error, std::abs(recovered[index] - impulse[index]));
    }
    if (!std::isfinite(scaling_error) || scaling_error > 1e-12 ||
        forward_flags == std::numeric_limits<unsigned>::max() ||
        backward_flags == std::numeric_limits<unsigned>::max()) {
        std::cerr << "FFTW planner observation or FFT scaling check failed\n";
        return 1;
    }

    // Failure boundaries: later transforms change scale or repeatedly plan.
    // Count actual planner calls; do not infer reuse from absent CPU samples.
    for (int repetition = 0; repetition < 100; ++repetition) {
        const auto repeated_spectrum = itpp::fft(impulse);
        const auto repeated_time = itpp::ifft(repeated_spectrum);
        for (int index = 0; index < 256; ++index) {
            if (std::abs(repeated_time[index] - impulse[index]) > 1e-12) {
                std::cerr << "Repeated FFT scaling check failed\n";
                return 1;
            }
        }
    }

    const auto expected = serial_samples(false);
    const auto expected_reseeded = serial_samples(true);
    bool same_seed_match = true;
    bool reseed_independent = true;
    for (int repetition = 0; repetition < 8; ++repetition) {
        std::array<std::vector<itpp::cvec>, 2> samples;
        for (auto& worker_samples : samples) {
            worker_samples.resize(sample_count);
        }
        std::barrier step(2);
        auto worker = [&](int worker_index) {
            itpp::RNG_reset(seed);
            step.arrive_and_wait();
            for (int index = 0; index < sample_count; ++index) {
                if (worker_index == 0) {
                    samples[0][index] = draw();
                }
                step.arrive_and_wait();
                if (worker_index == 1) {
                    if (index == sample_count / 2) {
                        itpp::RNG_reset(reseed);
                    }
                    samples[1][index] = draw();
                }
                step.arrive_and_wait();
            }
        };
        std::thread first(worker, 0);
        std::thread second(worker, 1);
        first.join();
        second.join();
        same_seed_match &= matches(samples[0], expected, 0, sample_count / 2) &&
                           matches(samples[1], expected, 0, sample_count / 2);
        reseed_independent &= matches(samples[0], expected, sample_count / 2, sample_count) &&
                              matches(samples[1], expected_reseeded,
                                      sample_count / 2, sample_count);
    }

    std::cout << std::boolalpha
              << "{\"fftw_forward_flags\":" << forward_flags
              << ",\"fftw_backward_flags\":" << backward_flags
              << ",\"fftw_forward_plans\":" << forward_plans
              << ",\"fftw_backward_plans\":" << backward_plans
              << ",\"fft_calls_per_direction\":101"
              << ",\"fft_scaling_max_abs_error\":" << scaling_error
              << ",\"rng_same_seed_two_threads_match\":" << same_seed_match
              << ",\"rng_cross_thread_reseed_independent\":" << reseed_independent
              << ",\"rng_seed_bits\":" << std::numeric_limits<unsigned>::digits
              << "}\n";
}
