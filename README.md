# Anaerobic Digester + Cogeneration Plant Simulation

**ME 401 Thermodynamics III -- Project 2**
Boise State University, Spring 2026

## Overview

This project models a wastewater treatment plant that uses **anaerobic digestion** to convert sewage sludge into biogas, which then fuels a **steam Rankine cogeneration (CHP) plant** to produce electricity and useful heat. The simulation compares this approach to conventional grid-powered operation and determines the conditions under which the plant can achieve energy self-sufficiency.

## System Description

1. **Anaerobic Digester (CSTR)**: Wastewater sludge enters a continuously stirred tank reactor operating at mesophilic conditions (35°C). Organic matter is broken down by anaerobic bacteria, producing biogas (60% methane, 40% CO2) at a rate of 0.4 m³ CH4 per m³ of reactor volume per day.

2. **Cogeneration Plant (Steam Rankine)**: Biogas is combusted in a boiler to produce superheated steam (6 MPa, 450°C). Steam expands through an extraction turbine — part is bled off at intermediate pressure (500 kPa) to provide process heat for digester heating, and the remainder expands to condenser pressure (10 kPa).

3. **Coupling**: The CHP extraction fraction is solved iteratively so that process heat delivered equals digester heating demand (sludge warming + wall losses).

## Quick Start

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the full simulation (generates plots + JSON output)
python -m src.driver

# Run unit tests
python -m pytest tests/ -v
```

## Project Structure

```
ME401-Project2/
    src/
        digester.py           # Anaerobic digester CSTR model
        cogeneration.py       # Steam Rankine CHP model
        driver.py             # Simulation driver, sweeps, optimization, plots
    tests/
        test_digester.py      # 21 digester unit tests
        test_cogeneration.py  # 28 CHP unit tests
        test_integration.py   # 10 integration tests
    report/
        report.tex            # Original LaTeX technical report (v1)
        report_v2.tex         # Revised technical report (v2, use this one)
        ai_use_report.tex     # AI use documentation report
        System_flow_diagram.png
    output/
        fig1_volume_sweep.pdf
        fig2_boiler_pressure.pdf
        fig3_extraction_pressure.pdf
        fig4_energy_balance.pdf
        fig5_grid_comparison.pdf
        fig6_breakeven_population.pdf
        simulation_results.json
    Resources/
        Nthia-Neves2018_Article_...pdf   # Primary reference paper
        Project 2-1Instructions.pdf
        AI-prompts-log.md                # AI use log (course requirement)
    AI_transcripts/                      # Records of all AI sessions
    AGENTS.md
    README.md
    requirements.txt
```

## Key Results (Baseline: 3,000 m³ reactor, 100,000 population)

| Output | Value |
|--------|-------|
| Net electrical output | 104 kW |
| Process heat delivered | 166 kW |
| Electrical efficiency | 20.9% |
| CHP efficiency | 54.2% |
| Grid offset | 41.6% |
| Simple payback period | 2.9 years |
| CO₂ avoided (annual) | 365 tonnes |

**Self-sufficiency** requires a reactor volume of ~7,157 m³ (serving ~240,000 people).

## References

- Náthia-Neves et al. (2018). "Anaerobic digestion process: technological aspects and recent developments." *Int. J. Environ. Sci. Technol.*, 15, 2033–2046.
- Çengel & Boles, *Thermodynamics: An Engineering Approach*, 8th ed. McGraw-Hill, 2015.
- Bell et al. (2014). "CoolProp: An open-source thermophysical property library." *Ind. Eng. Chem. Res.*, 53(6), 2498–2508.
