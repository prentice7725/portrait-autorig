# AR06 Physics Contract

The preview keeps the existing semi-implicit fixed-step spring and finite
rollback. Controller inputs are sampled at each fixed tick's wall-time
position by linear interpolation between adjacent render samples. A catch-up
frame therefore supplies a separate input sample to each tick instead of
repeating the latest sample and creating an artificial velocity/acceleration
spike.

The runtime accepts at most 100 ms of elapsed time per rendered frame and
integrates at most four fixed ticks. When the backlog exceeds that window, it
drops the oldest excess and simulates the newest retained tick window. The QA
profiler records both drop events and cumulative dropped seconds. Reduced
motion and Edit clear the accumulator and refresh the input sample so resumed
physics does not differentiate across the paused interval.

R3 frequency, damping, lag, range, and maximum displacement controls share
finite/range validation. The preset selector applies its profile as well as
its numeric values; the panel reports the matching preset and the current
delta from Auto. The UI labels frequency in Hz, damping ratio as unitless, lag
in seconds, and range/displacement in reference pixels.

No FPS/jitter/stall trajectory report was run in this change, so this contract
still needs the plan's 30/60/120 FPS, jitter, stall, pause/resume, Edit, and
reduced-motion captures before the stability gate can be called visually
verified.
