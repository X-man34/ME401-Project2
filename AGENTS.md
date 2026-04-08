# AGENTS.md -- AI Agent Context

## Project Overview

This repository contains a coupled **anaerobic digester + cogeneration (CHP) plant** simulation for ME 401 (Thermodynamics III) at Boise State University. The system models energy recovery from wastewater sludge via biogas production and a steam Rankine cycle.

## Architecture

```
Wastewater Sludge --> [AnaerobicDigester] --> Biogas (CH4+CO2) --> [CogenerationPlant] --> Electricity + Heat
                            ^                                             |
                            +---- Process heat feedback (digester heating) +
```

### Key Files

| File | Purpose |
|------|---------|
| `src/digester.py` | `AnaerobicDigester` class -- CSTR model, methane/biogas production, heat demand |
| `src/cogeneration.py` | `CogenerationPlant` class -- Steam Rankine cycle with extraction, CoolProp states |
| `src/driver.py` | Main simulation driver -- parametric sweeps, optimization, plotting, JSON output |
| `tests/test_digester.py` | Unit tests for digester model |
| `tests/test_cogeneration.py` | Unit tests for CHP thermodynamic model |
| `tests/test_integration.py` | Integration tests for coupled system |
| `report/report.tex` | LaTeX technical report |
| `output/` | Generated plots (PNG/PDF) and `simulation_results.json` |

### Key Classes

**`DigesterParams`** (dataclass): Reactor volume, feed rate, COD/VS concentrations, temperatures, methane production rate.

**`AnaerobicDigester`**: Call `.evaluate()` to get a `DigesterOutput` with HRT, OLR, methane rate, biogas energy (kW), and heat demand (kW).

**`CHPParams`** (dataclass): Boiler/extraction/condenser pressures, superheat temperature, component efficiencies.

**`CogenerationPlant`**: Call `.evaluate(Q_fuel_kw, Q_process_demand_kw)` to get a `CHPOutput` with all 8 thermodynamic states, power/heat flows, and efficiencies. The extraction fraction is solved iteratively to match process heat demand.

### Baseline Parameters

- Methane production rate: 0.4 m3 CH4/(m3 reactor * day)
- VFA concentration: 4.0 g COD/L
- Biogas composition: 60% CH4, 40% CO2
- Mesophilic operation: 35 C
- Boiler: 6 MPa, 450 C superheat
- Extraction: 500 kPa
- Condenser: 10 kPa
- Turbine isentropic efficiency: 85%
- Pump isentropic efficiency: 80%
- Boiler efficiency: 85%

### Running

```bash
source venv/bin/activate
python -m src.driver          # Full simulation
python -m pytest tests/ -v    # Unit tests
```

### Dependencies

Python 3.12+, CoolProp, matplotlib, numpy, scipy. Install via `pip install -r requirements.txt`.

### Optimization

Three configurable optimization modes in `driver.py`:
1. **Self-sufficiency**: Minimize reactor volume such that CHP electrical output >= WWTP demand
2. **Max power**: Optimize boiler/extraction pressures and superheat to maximize net electrical output
3. **Max efficiency**: Optimize for highest overall CHP efficiency

All use `scipy.optimize` (bounded scalar or differential evolution).
