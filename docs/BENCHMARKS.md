# Benchmark Lab

JARVIS-OS benchmarks are designed to produce reproducible measurements rather than marketing numbers.

## Neural microbenchmark

Run locally:

```bash
python benchmarks/neural_benchmark.py --size 1000 --steps 1000 --repeats 3
```

The benchmark reports median, minimum and maximum runtime plus steps per second.

GitHub Actions runs the same benchmark when neural or benchmark code changes and stores the JSON result as an artifact.

## Interpreting results

Compare results only when the runner, Python version, workload and benchmark revision are known. A benchmark result is a measurement of that configuration, not a universal performance claim.
