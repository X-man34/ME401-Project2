# Anaerobic Digester + Cogeneration Plant Simulation

**ME 401 Thermodynamics III -- Project 2**
Boise State University, Spring 2026

## Overview

This project models a wastewater treatment plant that uses **anaerobic digestion** to convert sewage sludge into biogas, which then fuels a **steam Rankine cogeneration (CHP) plant** to produce electricity and useful heat. The simulation compares this approach to conventional grid-powered operation and determines the conditions under which the plant can achieve energy self-sufficiency.

## System Description

1. **Anaerobic Digester (CSTR)**: Wastewater sludge enters a continuously stirred tank reactor operating at mesophilic conditions (35 C). Organic matter is broken down by anaerobic bacteria, producing biogas (60% methane, 40% CO2) at a rate of 0.4 m3 CH4 per m3 of reactor volume per day.

2. **Cogeneration Plant (Steam Rankine)**: Biogas is combusted in a boiler to produce superheated steam (6 MPa, 450 C). Steam expands through an extraction turbine -- part is bled off at intermediate pressure (500 kPa) to provide process heat for digester heating, and the remainder expands to condenser pressure (10 kPa). All thermodynamic states are computed using CoolProp.

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
ME401 Project2/
    src/
        digester.py          # Anaerobic digester model
        cogeneration.py      # Steam Rankine CHP model (CoolProp)
        driver.py            # Simulation driver, sweeps, optimization, plots
    tests/
        test_digester.py     # 21 digester unit tests
        test_cogeneration.py # 28 CHP unit tests
        test_integration.py  # 10 integration tests
    report/
        report.tex           # LaTeX technical report
    output/
        fig1_volume_sweep.png/pdf
        fig2_boiler_pressure.png/pdf
        fig3_extraction_pressure.png/pdf
        fig4_energy_balance.png/pdf
        fig5_grid_comparison.png/pdf
        fig6_breakeven_population.png/pdf
        simulation_results.json
    Resources/               # Reference papers and project instructions
    AGENTS.md                # AI agent context
    README.md                # This file
    requirements.txt         # Python dependencies
```

## Key Results

The simulation answers three central questions from the project brief:

1. **Is biogas energy enough to power the plant?** Depends on scale. A 3,000 m3 reactor serving ~100,000 people can offset roughly 50-60% of plant electricity demand.

2. **How much grid electricity can be offset?** At baseline conditions, the CHP produces ~130 kW of net electrical power against a ~250 kW plant demand.

3. **What reactor volume achieves self-sufficiency?** Optimization finds the breakeven volume where CHP output equals WWTP electricity consumption.

## References

- Nathia-Neves et al. (2018). "Anaerobic digestion process: technological aspects and recent developments." *Int. J. Environ. Sci. Technol.*
- Cengel & Boles, *Thermodynamics: An Engineering Approach* (Rankine cycle theory)
- CoolProp thermodynamic library (coolprop.org)
