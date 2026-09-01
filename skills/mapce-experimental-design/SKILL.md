---
name: mapce-experimental-design
description: Design reproducible experiments for computer science, AI, and robotics using evidence retrieved from MAPCE. Use when planning research questions, hypotheses, baselines, datasets, robot tasks, metrics, controls, random seeds, repeated runs, ablations, sim-to-real evaluation, implementation checks, or reproduction studies. Trigger on “实验怎么设计”, “基线和消融”, “复现这篇论文”, “机器人评测方案”, and pre-data-collection methodology requests.
license: MIT
compatibility: Requires MAPCE MCP for literature- and code-grounded design.
metadata:
  version: "0.1.0"
---

# MAPCE Experimental Design

Design the experiment before data collection. Do not generate plausible-looking
results, sample sizes, hyperparameters, or hardware details that are not supplied or
supported by evidence.

## Establish the research claim

State the research question, testable hypothesis, unit of evaluation, intervention or
method change, comparator, outcomes, operating conditions, and intended scope. Separate
confirmatory questions from exploratory analyses.

Read `references/cs-ai-robotics.md` for domain-specific checks.

## Ground choices in MAPCE

Use `search_papers` to identify prior methods, accepted baselines, datasets, tasks,
metrics, and known failure cases. Deep-read the relevant sections with
`search_paper_content` and `read_paper_section`.

For reproduction or implementation work, inspect the paper's code status. When code
is indexed, use `search_code` with `paper_id` and repository filters to locate entry
points, configuration, symbols, tests, and dependencies. Record exact file and symbol
locators. Separate paper statements, code behavior, and unresolved details.

## Specify the design

Document:

- RQs and hypotheses;
- datasets, environments, robot platforms, tasks, and evaluation units;
- baselines and why each is included;
- independent variables, controls, nuisance factors, and held-constant settings;
- primary and secondary metrics with direction and aggregation;
- train/validation/test split, leakage controls, seeds, repeats, and run order;
- ablations tied to specific design claims;
- uncertainty reporting and planned statistical comparisons;
- compute, software, hardware, timing, and resource limits;
- stopping, failure, exclusion, and missing-run rules;
- safety constraints for real robots and human interaction;
- internal, construct, external, and conclusion validity threats.

Use `assets/experiment-design.md` as the output scaffold. Put executable run
combinations in `design/experiment-matrix.csv` with stable run IDs.

## Reproduction mode

Build a “known / missing / decision required” table. Never silently choose missing
hyperparameters from common practice. Recommend a pilot only when it is labeled as a
new design decision rather than a recovered paper setting.

## Review gate

Before experiments begin, ask the user to approve primary metrics, baselines, data
splits, compute budget, safety limits, and deviations from cited work. Update the plan
when any of these change.
