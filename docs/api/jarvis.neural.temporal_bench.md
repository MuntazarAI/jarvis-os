# `jarvis.neural.temporal_bench`

## Members

### `accuracy` (function)

_No docstring._

### `baseline_instant` (function)

Memoryless: fires only when both pulses share a tick.

### `baseline_moving_average` (function)

Rate window: fires when recent pulse density is high. Catches

### `build_coincidence_detector` (function)

3-neuron SNN: relays 0,1 -> output 2 (delay 1, w 2/3, threshold

### `make_trials` (function)

Half coincident (|dt| <= WINDOW), half separated (GAP_LO..GAP_HI).

### `run_benchmark` (function)

_No docstring._

### `snn_predict` (function)

_No docstring._
