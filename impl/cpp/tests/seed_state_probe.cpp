#include <itpp/itbase.h>
#include <bit>
#include <cmath>
#include <cstdint>
#include <iostream>

uint64_t next_splitmix(uint64_t& state) {
    state += 0x9e3779b97f4a7c15ULL;
    uint64_t value = state;
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31);
}

int main() {
    itpp::RNG_reset(1);
    itpp::ivec state;
    itpp::RNG_get_state(state);
    std::cout << "words=" << state.size() << '\n';
    uint64_t stream = 1;
    for (int i = 0; i < state.size(); ++i)
        state[i] = std::bit_cast<int>(uint32_t(next_splitmix(stream)));
    itpp::RNG_set_state(state);
    auto uniform = itpp::randu(1000);
    auto gaussian = itpp::randn(1000);
    int invalid = 0;
    for (int i = 0; i < 1000; ++i)
        invalid += !std::isfinite(uniform[i]) || uniform[i] < 0 || uniform[i] >= 1
                   || !std::isfinite(gaussian[i]);
    std::cout << "invalid_draws=" << invalid << '\n';
    return invalid ? 1 : 0;
}
