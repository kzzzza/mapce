# CS, AI, and Robotics Design Checks

## Machine learning and systems

- Prevent train/test contamination and tuning on the final benchmark.
- Give every baseline a fair implementation, search budget, data budget, and compute budget.
- Define preprocessing, checkpoints, stopping rules, and metric aggregation.
- Use independent seeds or runs; do not treat repeated measurements from one run as
  independent replicates.
- Report variance or intervals when stochasticity matters.
- Match each ablation to a claimed component or mechanism.
- Include latency, throughput, memory, energy, or cost when the claim concerns efficiency.

## Robotics

- Define task success, horizon, resets, interventions, and failure conditions.
- Separate simulation, replay, laboratory, and real-world evidence.
- Record robot model, sensors, control frequency, calibration, environment layout,
  payload, and safety stop behavior.
- Randomize or balance environment order, object instances, starting states, and operators.
- Report sim-to-real changes and real-world exclusions.
- Use staged safety gates before autonomous hardware runs.

## Validity

- Internal: leakage, confounding, inconsistent baseline tuning, implementation bugs.
- Construct: whether metrics measure the intended capability.
- External: domains, embodiments, datasets, and environments not represented.
- Conclusion: insufficient repeats, multiple comparisons, unstable estimates, or
  unsupported causal language.
