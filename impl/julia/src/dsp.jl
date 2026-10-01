using FFTW, Random, LinearAlgebra, Statistics

const FFT_SIZE = 256
const CP_LENGTH = 32
const SYMBOLS_PER_BATCH = 256
const BITS_PER_SYMBOL = 672
const BATCH_BITS = UInt64(SYMBOLS_PER_BATCH * BITS_PER_SYMBOL)
const SQRT10 = sqrt(10.0)
const GRAY_LEVELS = (-3, -1, 3, 1)

function splitmix(seed::UInt64)
    value = seed + 0x9e3779b97f4a7c15
    value = (value ⊻ (value >> 30)) * 0xbf58476d1ce4e5b9
    value = (value ⊻ (value >> 27)) * 0x94d049bb133111eb
    return value ⊻ (value >> 31)
end
batch_seed(master, point, batch) = splitmix(splitmix(splitmix(UInt64(master)) ⊻ UInt64(point)) ⊻ UInt64(batch))
noise_variance(point) = 216.0 / (672 * 10.0^(point / 10))
decode(values) = ComplexF64[complex(pair[1], pair[2]) for pair in values]
encode(values) = [[real(x), imag(x)] for x in values]

function map_qam(bits)
    return ComplexF64[complex(GRAY_LEVELS[2bits[i] + bits[i+1] + 1],
        GRAY_LEVELS[2bits[i+2] + bits[i+3] + 1]) / SQRT10 for i in 1:4:length(bits)]
end
function demap(values)
    bits = UInt8[]
    sizehint!(bits, 4length(values))
    for value in values, axis in (real(value), imag(value))
        scaled = axis * SQRT10
        push!(bits, scaled >= 0, -2 <= scaled < 2)
    end
    return bits
end
function convolve(values, taps)
    output = zeros(ComplexF64, length(values))
    for delay in 0:length(taps)-1, n in delay+1:length(values)
        output[n] += taps[delay+1] * values[n-delay]
    end
    return output
end
function equalize(data, estimates)
    output = similar(data)
    zeros_count = UInt64(0)
    for i in eachindex(data)
        if iszero(estimates[i])
            output[i] = 0
            zeros_count += 1
        else
            output[i] = data[i] / estimates[i]
        end
    end
    return output, zeros_count
end

struct Geometry
    data_indices::Vector{Int}
    pilot_indices::Vector{Int}
    pilots::Vector{Float64}
    left::Vector{Int}
    right::Vector{Int}
    fraction::Vector{Float64}
    tap_scales::Vector{Float64}
    awgn::Bool
    perfect::Bool
end
function Geometry(config)
    bins = Int.(config.pilot_bins)
    data = Int.(config.data_bins)
    right = [searchsortedlast(bins, k) + 1 for k in data]
    left = right .- 1
    fraction = [(k - bins[l]) / (bins[r] - bins[l]) for (k, l, r) in zip(data, left, right)]
    return Geometry(mod.(data, FFT_SIZE) .+ 1, mod.(bins, FFT_SIZE) .+ 1,
        Float64.(config.pilots), left, right, fraction, sqrt.(Float64.(config.pdp) ./ 2),
        config.channel == "awgn", config.csi == "perfect")
end
mutable struct Worker{F,I}
    geometry::Geometry
    forward::F
    backward::I
    rng::Xoshiro
end
function Worker(geometry)
    buffer = zeros(ComplexF64, FFT_SIZE)
    return Worker(geometry, plan_fft(buffer; flags=FFTW.ESTIMATE),
        plan_bfft(buffer; flags=FFTW.ESTIMATE), Xoshiro(0))
end
# ponytail: symbol-sized temporaries keep the teaching path readable after M8;
# full worker buffer reuse belongs to a separate optimized benchmark revision.
function forward(w, values)
    output = w.forward * values
    output ./= sqrt(FFT_SIZE)
    return output
end
function backward(w, values)
    output = w.backward * values
    output ./= sqrt(FFT_SIZE)
    return output
end
add_cp(values) = vcat(values[end-CP_LENGTH+1:end], values)
remove_cp(values) = values[CP_LENGTH+1:CP_LENGTH+FFT_SIZE]
bits(w) = rand(w.rng, UInt8, BITS_PER_SYMBOL) .& 0x01
function taps(w)
    w.geometry.awgn && return ComplexF64[1]
    return ComplexF64[complex(randn(w.rng), randn(w.rng)) * scale for scale in w.geometry.tap_scales]
end
function grid(w, values)
    output = zeros(ComplexF64, FFT_SIZE)
    output[w.geometry.data_indices] = values
    output[w.geometry.pilot_indices] = w.geometry.pilots
    return output
end
function estimate(w, spectrum)
    geometry = w.geometry
    pilots = spectrum[geometry.pilot_indices] ./ geometry.pilots
    return pilots, pilots[geometry.left] .+ geometry.fraction .* (pilots[geometry.right] .- pilots[geometry.left])
end
function response(w, taps)
    padded = zeros(ComplexF64, FFT_SIZE)
    padded[1:length(taps)] = taps
    # Channel gains use the unscaled tap DFT, even with unitary signal FFTs.
    return w.forward * padded
end
awgn(w, values, n0) = ComplexF64[v + complex(randn(w.rng), randn(w.rng)) * sqrt(n0/2) for v in values]
function decide(values, original)
    errors = UInt64(count(demap(values) .!= original))
    return errors, UInt64(errors > 0)
end
function batch(w, seed, point)
    Random.seed!(w.rng, seed)
    errors = UInt64(0)
    symbols_with_errors = UInt64(0)
    zeros_count = UInt64(0)
    for _ in 1:SYMBOLS_PER_BATCH
        original = bits(w)
        transmit_grid = grid(w, map_qam(original))
        transmit_time = backward(w, transmit_grid)
        prefixed = add_cp(transmit_time)
        channel_taps = taps(w)
        received = awgn(w, convolve(prefixed, channel_taps), noise_variance(point))
        received_grid = forward(w, remove_cp(received))
        estimates = w.geometry.perfect ? response(w, channel_taps)[w.geometry.data_indices] : estimate(w, received_grid)[2]
        equalized, z = equalize(received_grid[w.geometry.data_indices], estimates)
        e, s = decide(equalized, original)
        errors += e
        symbols_with_errors += s
        zeros_count += z
    end
    return (n_batches=UInt64(1), n_errors=errors, sum_batch_errors_sq=errors^2,
        n_symbols_with_errors=symbols_with_errors, zf_zero_count=zeros_count)
end
function stage_actions(w, seed, point)
    Random.seed!(w.rng, seed)
    original = [bits(w) for _ in 1:SYMBOLS_PER_BATCH]
    qam = map(map_qam, original)
    spectra = [grid(w, x) for x in qam]
    values = [backward(w, x) for x in spectra]
    prefixed = map(add_cp, values)
    retained_taps = [taps(w) for _ in original]
    channel = [convolve(x, h) for (x, h) in zip(prefixed, retained_taps)]
    noisy = [awgn(w, x, noise_variance(point)) for x in channel]
    stripped = map(remove_cp, noisy)
    received = [forward(w, x) for x in stripped]
    estimates = [estimate(w, x)[2] for x in received]
    data = [x[w.geometry.data_indices] for x in received]
    equalized = [equalize(x, h)[1] for (x, h) in zip(data, estimates)]
    return [
        "bits" => () -> [bits(w) for _ in original],
        "qam_map" => () -> map(map_qam, original),
        "grid" => () -> [grid(w, x) for x in qam],
        "ifft" => () -> [backward(w, x) for x in spectra],
        "cp_add" => () -> map(add_cp, values),
        "channel_conv" => () -> [convolve(x, h) for (x, h) in zip(prefixed, retained_taps)],
        "awgn" => () -> [awgn(w, x, noise_variance(point)) for x in channel],
        "cp_remove" => () -> map(remove_cp, noisy),
        "fft" => () -> [forward(w, x) for x in stripped],
        "chan_est" => () -> [estimate(w, x) for x in received],
        "zf" => () -> [equalize(x, h) for (x, h) in zip(data, estimates)],
        "demap_count" => () -> [decide(x, b) for (x, b) in zip(equalized, original)],
    ]
end
function stage_timings(w, actions, seed, point, repetitions)
    timings = Dict{String,Float64}()
    for (name, action) in actions
        samples = Float64[]
        for _ in 1:repetitions
            start = time_ns()
            action()
            push!(samples, (time_ns() - start) / SYMBOLS_PER_BATCH)
        end
        timings[name] = median(samples)
    end
    samples = Float64[]
    for repetition in 0:repetitions-1
        start = time_ns()
        batch(w, batch_seed(seed, 0, repetition), point)
        push!(samples, (time_ns() - start) / SYMBOLS_PER_BATCH)
    end
    timings["e2e"] = median(samples)
    return timings
end
function golden(w, case_id, inputs)
    case_id == "qam_map" && return Dict("symbols" => encode(map_qam(inputs.bits)))
    case_id == "demap" && return Dict("bits" => demap(decode(inputs.symbols)))
    if case_id == "grid"
        spectrum = grid(w, decode(inputs.symbols))
        return Dict("spectrum" => encode(spectrum), "data" => encode(spectrum[w.geometry.data_indices]),
            "pilots" => encode(spectrum[w.geometry.pilot_indices]))
    elseif case_id in ("transforms", "fft_impulse")
        values = decode(inputs.values)
        return Dict("fft" => encode(forward(w, values)), "ifft" => encode(backward(w, values)))
    elseif case_id == "cp"
        prefixed = add_cp(decode(inputs.values))
        return Dict("with_cp" => encode(prefixed), "without_cp" => encode(remove_cp(prefixed)))
    elseif case_id == "channel"
        h = decode(inputs.taps)
        return Dict("convolved" => encode(convolve(decode(inputs.values), h)), "response" => encode(response(w, h)))
    elseif case_id == "estimation"
        pilots, data = estimate(w, decode(inputs.spectrum))
        return Dict("pilot_estimates" => encode(pilots), "data_estimates" => encode(data))
    elseif case_id == "zf"
        values, z = equalize(decode(inputs.data), decode(inputs.estimates))
        return Dict("equalized" => encode(values), "zf_zero_count" => z)
    elseif case_id == "noise_seed"
        # Typed raw integers in main.jl preserve all 64 bits of golden inputs.
        return Dict("N0" => noise_variance.(inputs.ebn0_db),
            "splitmix_outputs" => splitmix.(UInt64.(inputs.splitmix_inputs)),
            "batch_seeds" => [batch_seed(triple...) for triple in inputs.batch_seed_inputs])
    end
    case_id == "end_to_end" || error("Unknown golden case: $case_id")
    original = UInt8.(inputs.bits)
    h = decode(inputs.taps)
    spectrum = grid(w, map_qam(original))
    values = backward(w, spectrum)
    prefixed = add_cp(values)
    received = convolve(prefixed, h) .+ decode(inputs.noise)
    received_grid = forward(w, remove_cp(received))
    pilots, estimates = estimate(w, received_grid)
    data = received_grid[w.geometry.data_indices]
    equalized, z = equalize(data, estimates)
    perfect = equalize(data, response(w, h)[w.geometry.data_indices])[1]
    decoded = demap(equalized)
    return Dict("spectrum" => encode(spectrum), "time" => encode(values), "with_cp" => encode(prefixed),
        "received" => encode(received), "received_fft" => encode(received_grid), "pilot_estimates" => encode(pilots),
        "data_estimates" => encode(estimates), "equalized" => encode(equalized), "bits" => decoded,
        "perfect_bits" => demap(perfect), "n_errors" => count(decoded .!= original), "zf_zero_count" => z)
end
