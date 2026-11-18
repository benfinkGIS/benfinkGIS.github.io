# Step 10 (called by 18_gaps.py): rerun Omniscape around each candidate gap,
# once as the ground is and once with the gap repaired, and write the change
# in current.
#
# A repair changes resistance in a few cells. Only moving windows that contain
# one of those cells can give a different answer, and each of those windows
# reaches one radius further. So each job is run on a cut-out of the grid that
# reaches two radii beyond the repair, and only on the windows centered within
# one radius of it. The difference between the two runs is then the same as the
# difference between two runs of the whole grid on the same window centers.
#
#   julia --project=tools/washes/julia -t N tools/washes/julia/gaps.jl <folder>
#
# <folder> holds jobs.tsv, <species>_{base,fixed,source}.bin (Float64, rows
# first, as numpy writes them) and fp_<id>.bin (Int32 row, column pairs,
# counted from 1). Writes delta_<id>.bin (Float32, rows first) and done.tsv.
using Omniscape

const DIR = ARGS[1]
const SCRATCH = joinpath(DIR, "_omniscape")

# The cells of the repair in cut-out coordinates, and how far a window center
# may be from them. Nothing: keep every window.
const NEAR = Ref{Union{Nothing, Tuple{Vector{Int}, Vector{Int}, Int}}}(nothing)

# Omniscape picks its window centers in get_targets. This method takes the
# place of the package's for double precision, calls the package's own, and
# drops the centers too far from the repair to be changed by it.
function Omniscape.get_targets(s::Array{Union{Float64, Missing}, 2}, a::Dict{String, Int64},
                               p::Type{Float64})
    t = invoke(Omniscape.get_targets,
               Tuple{Array{Union{T, Missing}, 2} where T <: Number, Dict{String, Int64}, DataType},
               s, a, p)
    NEAR[] === nothing && return t
    rows, cols, reach = NEAR[]
    keep = [any((rows .- t[i, 2]) .^ 2 .+ (cols .- t[i, 1]) .^ 2 .<= reach^2) for i in 1:size(t, 1)]
    t[keep, :]
end

function solve(res, src, radius, block)
    rm(SCRATCH; force = true, recursive = true)
    cfg = Dict("radius" => string(radius), "block_size" => string(block),
               "project_name" => SCRATCH, "source_from_resistance" => "false",
               "calc_normalized_current" => "false", "calc_flow_potential" => "false",
               "parallelize" => "true", "parallel_batch_size" => "4",
               "solver" => "cg+amg", "precision" => "double")
    out = run_omniscape(cfg, convert(Array{Union{Float64, Missing}, 2}, res);
                        source_strength = convert(Array{Union{Float64, Missing}, 2}, src))
    Float64.(coalesce.(out, 0.0))
end

function main()
    lines = [split(l, '\t') for l in readlines(joinpath(DIR, "jobs.tsv"))]
    nr, nc = parse.(Int, lines[1][1:2])
    grids = Dict{String, Matrix{Float64}}()
    grid(name) = get!(grids, name) do
        permutedims(read!(joinpath(DIR, name * ".bin"), Array{Float64}(undef, nc, nr)))
    end
    done = joinpath(DIR, "done.tsv")
    finished = isfile(done) ? Set(first.(split.(readlines(done), '\t'))) : Set{String}()
    for l in lines[2:end]
        id, sp = String(l[1]), String(l[2])
        id in finished && continue
        r0, r1, c0, c1, radius, block, every = parse.(Int, l[3:9])
        fp = read!(joinpath(DIR, "fp_$id.bin"), Array{Int32}(undef, 2, filesize(joinpath(DIR, "fp_$id.bin")) ÷ 8))
        rows, cols = Int.(fp[1, :]), Int.(fp[2, :])
        base = grid(sp * "_base")[r0:r1, c0:c1]
        fixed = copy(base)
        all_fixed = grid(sp * "_fixed")
        for (r, c) in zip(rows, cols)
            fixed[r - r0 + 1, c - c0 + 1] = all_fixed[r, c]
        end
        src = grid(sp * "_source")[r0:r1, c0:c1]
        NEAR[] = every == 1 ? nothing : (rows .- (r0 - 1), cols .- (c0 - 1), radius + block + 2)
        t = time()
        before = solve(base, src, radius, block)
        after = solve(fixed, src, radius, block)
        NEAR[] = nothing
        write(joinpath(DIR, "delta_$id.bin"), Float32.(permutedims(after .- before)))
        open(done, "a") do io
            println(io, join([id, round(time() - t; digits = 1), sum(before), sum(after)], '\t'))
        end
        println("done $id in $(round(time() - t; digits = 1)) s")
        flush(stdout)
    end
end

main()
