using Profile

# Failure boundaries: JIT mistaken for work, lost samples, changed counters,
# and a profiler buffer too small for the complete retained workload.
include(joinpath(@__DIR__, "../impl/julia/src/main.jl"))
before = JSON3.read(read(args.output, String))
Profile.init(n=10^7, delay=0.01)
Profile.clear()
Profile.@profile execute(args)
after = JSON3.read(read(args.output, String))
for key in (:n_batches, :n_bits, :n_errors, :sum_batch_errors_sq,
            :n_symbols_with_errors, :zf_zero_count)
    @assert before[key] == after[key]
end
@assert !isempty(Profile.fetch())
open(args.output * ".profile.txt", "w") do file
    Profile.print(file; format=:flat, sortedby=:count, mincount=5)
end
# Retain the raw instruction pointers and their resolved source frames.
data, frames = Profile.retrieve()
open(args.output * ".profile-raw.txt", "w") do file
    show(file, data)
    println(file)
    show(file, frames)
end
