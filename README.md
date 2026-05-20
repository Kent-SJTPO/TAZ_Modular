# TAZ_Modular

Modular workflow for updating SJTDM TAZ geography using 2020 Census blocks.

Design principles:
- deterministic staged processing
- stable intermediate outputs
- geometry QA/QC before aggregation
- auditable transformation steps
- iterative human-assisted refinement

Primary workflow stages:
1. Normalize geometry and CRS
2. QA/QC geometry
3. Repair or remove invalid geometry
4. Assign blocks to candidate TAZs
5. Aggregate 2020 blocks into TAZ polygons
6. Compare against legacy 2011 TAZ geometry
7. Iterate manual adjustments until tolerance thresholds are met

Repository structure:

config/         Shared paths, CRS definitions, tolerances, settings
data_samples/   Small sample datasets for testing and debugging
docs/           Workflow notes, QA procedures, environment documentation
outputs/        Generated intermediate and final outputs (not versioned)
scripts/        Modular processing scripts
tests/          Validation and regression testing scripts

Processing Philosophy

Each stage should:
- consume stable prior outputs
- produce deterministic outputs
- avoid modifying upstream data
- preserve auditable intermediate artifacts
- minimize side effects outside the stage boundary