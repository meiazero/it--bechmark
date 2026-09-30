#include "dsp.hpp"
#include <fstream>
#include <iostream>
#include <stdexcept>

Json sequence(Worker& worker, U64 seed) {
    worker.seed(seed);
    return {{"bits", worker.bits()}, {"taps", encode(worker.taps())},
            {"noise", encode(worker.awgn(Values(288), 1))}};
}

int main(int argc, char** argv) {
    try {
        if (argc != 3) throw std::runtime_error("Expected config and artifact paths");
        std::ifstream input(argv[1]);
        auto config = Json::parse(input);
        Worker worker(config);
        auto first = sequence(worker, 7);
        auto repeated = sequence(worker, 7);
        auto upper = sequence(worker, (U64(1) << 32) | 7);
        if (first != repeated || first == upper)
            throw std::runtime_error("Full-u64 sequence test failed");
        for (const std::string field : {"bits", "taps", "noise"})
            if (first[field] == upper[field])
                throw std::runtime_error("Upper seed bits did not change " + field);
        std::ofstream output(argv[2]);
        output << Json{{"seed", 7}, {"upper_seed", (U64(1) << 32) | 7},
                       {"first", first}, {"repeated", repeated}, {"upper", upper}}.dump(2) << '\n';
        if (!output) throw std::runtime_error("Cannot write seed artifact");
        std::cout << "PASS full-u64 bits, taps, and noise sequences\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
