const SETUP_START = time_ns()
using JSON3, SHA
const ROOT = normpath(joinpath(@__DIR__, "../../.."))
const U64_MAX = big(typemax(UInt64))

# JSON3 owns JSON syntax. Its RawType extension lets Julia's integer parser
# reject fractions and preserve seeds above Int64 without a Float64 round trip.
struct ExactInteger
    value::BigInt
end
JSON3.StructTypes.StructType(::Type{ExactInteger}) = JSON3.RawType()
function JSON3.StructTypes.construct(::Type{ExactInteger}, raw::JSON3.RawValue)
    token = String(Vector{UInt8}(raw.bytes[raw.pos:raw.pos+raw.len-1]))
    occursin(r"^-?(0|[1-9][0-9]*)$", token) || error("Expected an exact JSON integer")
    return ExactInteger(parse(BigInt, token))
end
function strict_json(bytes)
    value = JSON3.read(bytes)
    check_json(value)
    return value
end
function check_json(value)
    if value isa JSON3.Object
        seen = Set{Symbol}()
        for (key, item) in pairs(value)
            key in seen && error("Duplicate JSON key: $key")
            push!(seen, key)
            check_json(item)
        end
    elseif value isa AbstractVector
        foreach(check_json, value)
    elseif value isa Number
        isfinite(value) || error("Non-finite JSON number")
    end
end
function object_keys(value, reference)
    value isa JSON3.Object && Set(keys(value)) == Set(keys(reference)) || error("Object keys differ")
end
function integer(value::ExactInteger, name; minimum=1, maximum=U64_MAX)
    minimum <= value.value <= maximum || error("$name outside the permitted integer range")
    return UInt64(value.value)
end
const BER_INTEGERS = NamedTuple{(:target_errors, :min_batches, :max_bits),Tuple{ExactInteger,ExactInteger,ExactInteger}}
const PERF_INTEGERS = NamedTuple{(:ebn0_db, :n_batches),Tuple{ExactInteger,Union{Nothing,ExactInteger}}}
const CONFIG_INTEGERS = NamedTuple{(:master_seed, :ber, :perf, :stages),
    Tuple{ExactInteger,BER_INTEGERS,PERF_INTEGERS,NamedTuple{(:repetitions,),Tuple{ExactInteger}}}}
function validate(config, bytes, mode)
    reference = strict_json(read(joinpath(ROOT, "contract/profile_main.json")))
    object_keys(config, reference)
    for name in (:schema_version, :profile_id, :N_fft, :N_cp, :M, :active_bins,
        :pilot_bins, :data_bins, :pilots, :pdp, :E_sym, :bits_per_symbol, :B, :warmup_batches)
        typeof(config[name]) == typeof(reference[name]) && config[name] == reference[name] || error("$name differs from frozen profile")
    end
    for name in (:ber, :perf, :stages)
        object_keys(config[name], reference[name])
    end
    config.channel in ("awgn", "rayleigh") || error("Unknown channel")
    config.csi in ("perfect", "estimated") || error("Unknown CSI")
    exact = JSON3.read(bytes, CONFIG_INTEGERS)
    master = integer(exact.master_seed, "master_seed"; minimum=0)
    target = integer(exact.ber.target_errors, "target_errors")
    minimum = integer(exact.ber.min_batches, "min_batches")
    maximum = integer(exact.ber.max_bits, "max_bits"; maximum=U64_MAX-172032+1)
    big(minimum) * 172032 <= maximum || error("max_bits below minimum batch payload")
    config.ber.ebn0_db isa AbstractVector && !isempty(config.ber.ebn0_db) || error("Empty Eb/N0 points")
    for point in config.ber.ebn0_db
        point isa Real && !(point isa Bool) || error("Expected a finite Eb/N0 number")
        n0 = 216.0 / (672 * 10.0^(point / 10))
        isfinite(n0) && n0 > 0 || error("Eb/N0 exceeds finite noise range")
    end
    integer(exact.perf.ebn0_db, "perf.ebn0_db") == 10 || error("perf Eb/N0 must be 10")
    batches = exact.perf.n_batches === nothing ? nothing : integer(exact.perf.n_batches, "perf.n_batches"; maximum=U64_MAX÷172032)
    mode == "perf" && batches === nothing && error("perf.n_batches awaits M8 calibration")
    repetitions = integer(exact.stages.repetitions, "stages.repetitions")
    mode in ("perf", "stages") && config.csi != "estimated" && error("Perfect CSI is diagnostic only")
    # Validate frozen integer fields through the same strict numeric extension.
    scalar_names = (:schema_version, :N_fft, :N_cp, :M, :E_sym, :bits_per_symbol, :B, :warmup_batches)
    scalar_type = NamedTuple{scalar_names,NTuple{length(scalar_names),ExactInteger}}
    scalars = JSON3.read(bytes, scalar_type)
    for name in scalar_names
        scalars[name].value == reference[name] || error("Invalid frozen integer")
    end
    vector_names = (:active_bins, :pilot_bins, :data_bins, :pilots)
    vector_type = NamedTuple{vector_names,NTuple{4,Vector{ExactInteger}}}
    vectors = JSON3.read(bytes, vector_type)
    for name in vector_names
        [x.value for x in vectors[name]] == reference[name] || error("Invalid frozen integer array")
    end
    return (; master, target, minimum, maximum, batches, repetitions)
end
function arguments()
    length(ARGS) == 8 || error("Usage: --config FILE --mode MODE --workers P --out FILE")
    options = Dict{String,String}()
    for i in 1:2:8
        key = ARGS[i]
        key in ("--config", "--mode", "--workers", "--out") && !haskey(options, key) || error("Unknown or duplicate CLI option")
        options[key] = ARGS[i+1]
    end
    mode = options["--mode"]
    mode in ("golden", "ber", "perf", "stages") || error("Unknown mode")
    occursin(r"^[1-9][0-9]*$", options["--workers"]) || error("workers must be positive u64")
    workers = parse(UInt64, options["--workers"])
    workers <= typemax(Int) || error("workers exceeds addressable range")
    workers == Threads.threadpoolsize(:default) || error("Launch Julia with --threads=$workers,0")
    bytes = read(options["--config"])
    config = strict_json(bytes)
    counters = validate(config, bytes, mode)
    return (; mode, workers=Int(workers), bytes, config, counters, output=options["--out"])
end

function execute(args)
    FFTW.set_num_threads(1)
    BLAS.set_num_threads(1)
    geometry = Geometry(args.config)
    base = Dict{String,Any}("schema_version" => 1, "impl" => "julia", "mode" => args.mode,
        "profile_id" => args.config.profile_id, "master_seed" => args.counters.master,
        "workers" => args.workers, "config_sha256" => bytes2hex(sha256(args.bytes)),
        "git_sha" => strip(read(`git -C $ROOT rev-parse HEAD`, String)))
    records = Dict{String,Any}[]
    if args.mode == "golden"
        worker = Worker(geometry)
        for path in sort(readdir(joinpath(ROOT, "contract/golden"); join=true))
            endswith(path, ".json") || continue
            bytes = read(path)
            vector = strict_json(bytes)
            inputs = vector.inputs
            if vector.case_id == "noise_seed"
                seed_type = NamedTuple{(:inputs,),Tuple{NamedTuple{(:ebn0_db, :splitmix_inputs, :batch_seed_inputs),
                    Tuple{Vector{Float64},Vector{ExactInteger},Vector{Vector{ExactInteger}}}}}}
                exact = JSON3.read(bytes, seed_type).inputs
                inputs = (ebn0_db=exact.ebn0_db, splitmix_inputs=[UInt64(x.value) for x in exact.splitmix_inputs],
                    batch_seed_inputs=[[UInt64(x.value) for x in triple] for triple in exact.batch_seed_inputs])
            end
            push!(records, merge(base, Dict("case_id" => vector.case_id, "outputs" => golden(worker, vector.case_id, inputs))))
        end
    else
        workers = [Worker(geometry) for _ in 1:args.workers]
        stage_worker = args.mode == "stages" ? Worker(geometry) : nothing
        setup_s = (time_ns() - SETUP_START) / 1e9
        start = time_ns()
        parallel_batches(workers, splitmix(args.counters.master ⊻ 0x00007761726d7570), 0, UInt64(0), UInt64(4), 10.0)
        stage_seed = batch_seed(args.counters.master, 0, 0)
        actions = stage_worker === nothing ? nothing : stage_actions(stage_worker, stage_seed, 10.0)
        if actions !== nothing
            for (_, action) in actions
                action()
            end
            # Compile the timing dispatcher during warmup, with independent seeds.
            stage_timings(stage_worker, actions, splitmix(stage_seed), 10.0, 1)
        end
        warmup_s = (time_ns() - start) / 1e9
        if haskey(ENV, "BENCH_PHASE_PATH")
            flags = Base.Filesystem.JL_O_WRONLY | Base.Filesystem.JL_O_CREAT | Base.Filesystem.JL_O_EXCL
            phase = Base.Filesystem.open(ENV["BENCH_PHASE_PATH"], flags, 0o600)
            try
                write(phase, "work\n")
            finally
                close(phase)
            end
        end
        points = args.mode == "ber" ? Float64.(args.config.ber.ebn0_db) : [10.0]
        for (index, point) in enumerate(points)
            counters = Dict(name => UInt64(0) for name in (:n_batches, :n_errors, :sum_batch_errors_sq, :n_symbols_with_errors, :zf_zero_count))
            limit = args.mode == "ber" ? cld(args.counters.maximum, BATCH_BITS) : args.mode == "perf" ? args.counters.batches : UInt64(1)
            first = UInt64(0)
            status = args.mode == "ber" ? "max_bits" : "fixed_work"
            start = time_ns()
            stop = false
            while first < limit && !stop
                last = first + min(limit-first, UInt64(max(4, 2args.workers)))
                for counts in parallel_batches(workers, args.counters.master, index-1, first, last, point)
                    for (name, value) in pairs(counts)
                        counters[name] = Base.Checked.checked_add(counters[name], value)
                    end
                    if args.mode == "ber"
                        if counters[:n_batches] >= args.counters.minimum && counters[:n_errors] >= args.counters.target
                            status, stop = "target_errors", true
                        elseif counters[:n_batches] * BATCH_BITS >= args.counters.maximum
                            stop = true
                        end
                    end
                    stop && break
                end
                first = last
            end
            timings = actions === nothing ? nothing : stage_timings(stage_worker, actions, stage_seed, point, args.counters.repetitions)
            work_s = (time_ns() - start) / 1e9
            record = merge(base, Dict(string(k) => v for (k, v) in counters), Dict(
                "ebn0_db" => point, "n_symbols" => counters[:n_batches]*256, "n_bits" => counters[:n_batches]*BATCH_BITS,
                "status" => status, "setup_s" => setup_s, "warmup_s" => warmup_s, "work_s" => work_s))
            timings !== nothing && (record["stage_ns_per_symbol"] = timings)
            push!(records, record)
        end
    end
    temporary = args.output * ".tmp." * string(getpid())
    try
        open(temporary, "w") do file
            for record in records
                println(file, JSON3.write(record))
            end
        end
        mv(temporary, args.output; force=true)
    finally
        isfile(temporary) && rm(temporary)
    end
end
const Counts = NamedTuple{(:n_batches, :n_errors, :sum_batch_errors_sq, :n_symbols_with_errors, :zf_zero_count),NTuple{5,UInt64}}
function parallel_batches(workers, master, point_index, first, last, point)
    output = Vector{Counts}(undef, Int(last-first))
    next = Threads.Atomic{Int}(0)
    @sync for worker in workers
        Threads.@spawn begin
            while true
                i = Threads.atomic_add!(next, 1)
                i >= length(output) && break
                output[i+1] = batch(worker, batch_seed(master, point_index, first+UInt64(i)), point)
            end
        end
    end
    return output
end

args = try
    arguments()
catch error
    println(stderr, "Invalid configuration: ", sprint(showerror, error))
    exit(2)
end
try
    include("dsp.jl")
    execute(args)
catch error
    println(stderr, "Execution failed: ", sprint(showerror, error, catch_backtrace()))
    exit(1)
end
