#!/usr/bin/env python3
"""
Driver script for the Anaerobic Digester + Cogeneration Plant simulation.

Runs the coupled digester-CHP model, performs parametric sweeps, optimization,
and generates all plots and output data.

Usage:
    python -m src.driver          (from project root)
    python src/driver.py          (from project root)
"""

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for saving figures
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import minimize_scalar, minimize

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.digester import AnaerobicDigester, DigesterParams, DigesterOutput, LHV_CH4
from src.cogeneration import CogenerationPlant, CHPParams, CHPOutput

OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Plot styling
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "figure.figsize": (8, 5),
    "figure.dpi": 150,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "font.size": 11,
    "axes.labelsize": 12,
    "axes.titlesize": 13,
    "legend.fontsize": 10,
})


# ---------------------------------------------------------------------------
# Grid-only baseline constants
# ---------------------------------------------------------------------------
GRID_ELECTRICITY_COST = 0.10  # $/kWh
GRID_CO2_INTENSITY = 0.40  # kg CO2/kWh
WWTP_SPECIFIC_ENERGY = 0.40  # kWh/m3 wastewater treated
POPULATION_SERVED = 100_000
WASTEWATER_PER_CAPITA = 0.15  # m3/person/day
CHP_CAPITAL_COST_PER_KW = 2500  # $/kW installed capacity (typical for small CHP)
NATURAL_GAS_COST = 0.03  # $/kWh thermal (comparison fuel)


# ---------------------------------------------------------------------------
# Core simulation function
# ---------------------------------------------------------------------------
def run_simulation(digester_params: DigesterParams,
                   chp_params: CHPParams) -> tuple[DigesterOutput, CHPOutput]:
    """Run the coupled digester-CHP simulation and return both outputs."""
    digester = AnaerobicDigester(digester_params)
    dig_out = digester.evaluate()

    chp = CogenerationPlant(chp_params)
    chp_out = chp.evaluate(
        Q_fuel_kw=dig_out.thermal_energy_biogas,
        Q_process_demand_kw=dig_out.heat_demand_total,
    )
    return dig_out, chp_out


# ---------------------------------------------------------------------------
# Parametric sweep functions
# ---------------------------------------------------------------------------
def sweep_reactor_volume(chp_params: CHPParams,
                         volumes: np.ndarray | None = None) -> dict:
    """Sweep reactor volume, keeping feed rate proportional (constant HRT=20d)."""
    if volumes is None:
        volumes = np.linspace(500, 10000, 40)

    results = {
        "volume": [], "methane_rate": [], "biogas_energy_kw": [],
        "W_net_elec_kw": [], "Q_process_kw": [], "heat_demand_kw": [],
        "eta_electrical": [], "eta_chp": [], "extraction_fraction": [],
    }

    for v in volumes:
        dp = DigesterParams(
            volume=v,
            feed_flow_rate=v / 20.0,  # constant HRT = 20 days
        )
        dig_out, chp_out = run_simulation(dp, chp_params)
        results["volume"].append(v)
        results["methane_rate"].append(dig_out.methane_rate)
        results["biogas_energy_kw"].append(dig_out.thermal_energy_biogas)
        results["W_net_elec_kw"].append(chp_out.W_net_electrical)
        results["Q_process_kw"].append(chp_out.Q_process)
        results["heat_demand_kw"].append(dig_out.heat_demand_total)
        results["eta_electrical"].append(chp_out.eta_electrical)
        results["eta_chp"].append(chp_out.eta_chp)
        results["extraction_fraction"].append(chp_out.extraction_fraction)

    return results


def sweep_boiler_pressure(digester_params: DigesterParams,
                          pressures_mpa: np.ndarray | None = None) -> dict:
    """Sweep boiler pressure at fixed digester conditions."""
    if pressures_mpa is None:
        pressures_mpa = np.linspace(1.0, 12.0, 30)

    results = {
        "p_boiler_mpa": [], "W_net_elec_kw": [], "eta_electrical": [],
        "eta_chp": [], "extraction_fraction": [],
    }

    for p_mpa in pressures_mpa:
        cp = CHPParams(p_boiler=p_mpa * 1e6)
        try:
            _, chp_out = run_simulation(digester_params, cp)
            results["p_boiler_mpa"].append(p_mpa)
            results["W_net_elec_kw"].append(chp_out.W_net_electrical)
            results["eta_electrical"].append(chp_out.eta_electrical)
            results["eta_chp"].append(chp_out.eta_chp)
            results["extraction_fraction"].append(chp_out.extraction_fraction)
        except Exception:
            continue  # Skip infeasible pressures

    return results


def sweep_extraction_pressure(digester_params: DigesterParams,
                              base_chp: CHPParams,
                              pressures_kpa: np.ndarray | None = None) -> dict:
    """Sweep extraction pressure."""
    if pressures_kpa is None:
        pressures_kpa = np.linspace(100, 1500, 30)

    results = {
        "p_extract_kpa": [], "W_net_elec_kw": [], "Q_process_kw": [],
        "eta_electrical": [], "eta_chp": [], "extraction_fraction": [],
    }

    for p_kpa in pressures_kpa:
        cp = CHPParams(
            p_boiler=base_chp.p_boiler,
            t_superheat=base_chp.t_superheat,
            p_extract=p_kpa * 1e3,
            p_condenser=base_chp.p_condenser,
            eta_turbine=base_chp.eta_turbine,
            eta_pump=base_chp.eta_pump,
            eta_boiler=base_chp.eta_boiler,
        )
        try:
            _, chp_out = run_simulation(digester_params, cp)
            if chp_out.extraction_fraction > 1.0 or chp_out.W_net_electrical < 0:
                continue
            results["p_extract_kpa"].append(p_kpa)
            results["W_net_elec_kw"].append(chp_out.W_net_electrical)
            results["Q_process_kw"].append(chp_out.Q_process)
            results["eta_electrical"].append(chp_out.eta_electrical)
            results["eta_chp"].append(chp_out.eta_chp)
            results["extraction_fraction"].append(chp_out.extraction_fraction)
        except Exception:
            continue

    return results


# ---------------------------------------------------------------------------
# Optimization
# ---------------------------------------------------------------------------
def optimize_for_self_sufficiency(chp_params: CHPParams,
                                  wwtp_demand_kw: float) -> dict:
    """
    Find the minimum reactor volume where CHP electrical output >= WWTP demand.

    Keeps HRT constant at 20 days (feed rate scales with volume).
    """
    def objective(v):
        dp = DigesterParams(volume=v, feed_flow_rate=v / 20.0)
        _, chp_out = run_simulation(dp, chp_params)
        return (chp_out.W_net_electrical - wwtp_demand_kw) ** 2

    result = minimize_scalar(objective, bounds=(500, 20000), method="bounded")
    v_opt = result.x

    # Verify
    dp = DigesterParams(volume=v_opt, feed_flow_rate=v_opt / 20.0)
    dig_out, chp_out = run_simulation(dp, chp_params)

    return {
        "optimal_volume_m3": v_opt,
        "optimal_feed_rate_m3_day": v_opt / 20.0,
        "optimal_hrt_days": 20.0,
        "W_net_electrical_kw": chp_out.W_net_electrical,
        "wwtp_demand_kw": wwtp_demand_kw,
        "surplus_kw": chp_out.W_net_electrical - wwtp_demand_kw,
        "methane_rate_m3_day": dig_out.methane_rate,
        "extraction_fraction": chp_out.extraction_fraction,
        "eta_chp": chp_out.eta_chp,
    }


def optimize_max_power(chp_params: CHPParams, volume: float = 3000.0) -> dict:
    """
    Optimize CHP parameters (boiler pressure, superheat, extraction pressure)
    to maximize net electrical output at a fixed reactor volume.
    """
    def objective(x):
        p_boiler, t_sh, p_ext = x
        cp = CHPParams(
            p_boiler=p_boiler * 1e6,
            t_superheat=t_sh,
            p_extract=p_ext * 1e3,
            eta_turbine=chp_params.eta_turbine,
            eta_pump=chp_params.eta_pump,
            eta_boiler=chp_params.eta_boiler,
        )
        dp = DigesterParams(volume=volume, feed_flow_rate=volume / 20.0)
        try:
            _, chp_out = run_simulation(dp, cp)
            if chp_out.extraction_fraction > 0.99 or chp_out.extraction_fraction < 0:
                return 1e6
            return -chp_out.W_net_electrical  # Minimize negative = maximize
        except Exception:
            return 1e6

    from scipy.optimize import differential_evolution
    bounds = [(2.0, 12.0), (300.0, 550.0), (200, 1200)]  # P_boiler MPa, T_sh C, P_ext kPa
    result = differential_evolution(objective, bounds, seed=42, maxiter=100, tol=1e-6)

    p_opt, t_opt, pe_opt = result.x
    cp_opt = CHPParams(
        p_boiler=p_opt * 1e6, t_superheat=t_opt, p_extract=pe_opt * 1e3,
        eta_turbine=chp_params.eta_turbine, eta_pump=chp_params.eta_pump,
        eta_boiler=chp_params.eta_boiler,
    )
    dp = DigesterParams(volume=volume, feed_flow_rate=volume / 20.0)
    dig_out, chp_out = run_simulation(dp, cp_opt)

    return {
        "optimal_p_boiler_mpa": p_opt,
        "optimal_t_superheat_c": t_opt,
        "optimal_p_extract_kpa": pe_opt,
        "W_net_electrical_kw": chp_out.W_net_electrical,
        "eta_electrical": chp_out.eta_electrical,
        "eta_chp": chp_out.eta_chp,
        "extraction_fraction": chp_out.extraction_fraction,
    }


def optimize_max_efficiency(chp_params: CHPParams, volume: float = 3000.0) -> dict:
    """Optimize CHP parameters to maximize overall CHP efficiency."""
    def objective(x):
        p_boiler, t_sh, p_ext = x
        cp = CHPParams(
            p_boiler=p_boiler * 1e6, t_superheat=t_sh, p_extract=p_ext * 1e3,
            eta_turbine=chp_params.eta_turbine, eta_pump=chp_params.eta_pump,
            eta_boiler=chp_params.eta_boiler,
        )
        dp = DigesterParams(volume=volume, feed_flow_rate=volume / 20.0)
        try:
            _, chp_out = run_simulation(dp, cp)
            if chp_out.extraction_fraction > 0.99:
                return 1e6
            return -chp_out.eta_chp
        except Exception:
            return 1e6

    from scipy.optimize import differential_evolution
    bounds = [(2.0, 12.0), (300.0, 550.0), (200, 1200)]
    result = differential_evolution(objective, bounds, seed=42, maxiter=100, tol=1e-6)

    p_opt, t_opt, pe_opt = result.x
    cp_opt = CHPParams(
        p_boiler=p_opt * 1e6, t_superheat=t_opt, p_extract=pe_opt * 1e3,
        eta_turbine=chp_params.eta_turbine, eta_pump=chp_params.eta_pump,
        eta_boiler=chp_params.eta_boiler,
    )
    dp = DigesterParams(volume=volume, feed_flow_rate=volume / 20.0)
    dig_out, chp_out = run_simulation(dp, cp_opt)

    return {
        "optimal_p_boiler_mpa": p_opt,
        "optimal_t_superheat_c": t_opt,
        "optimal_p_extract_kpa": pe_opt,
        "W_net_electrical_kw": chp_out.W_net_electrical,
        "eta_electrical": chp_out.eta_electrical,
        "eta_chp": chp_out.eta_chp,
        "extraction_fraction": chp_out.extraction_fraction,
    }


# ---------------------------------------------------------------------------
# Plotting functions
# ---------------------------------------------------------------------------
def plot_volume_sweep(results: dict, wwtp_demand_kw: float):
    """Plot net electrical output vs reactor volume with breakeven line."""
    fig, ax1 = plt.subplots()

    ax1.plot(results["volume"], results["W_net_elec_kw"],
             "b-", linewidth=2, label="Net Electrical Output")
    ax1.axhline(y=wwtp_demand_kw, color="r", linestyle="--", linewidth=1.5,
                label=f"WWTP Demand ({wwtp_demand_kw:.0f} kW)")
    ax1.set_xlabel("Reactor Volume (m$^3$)")
    ax1.set_ylabel("Net Electrical Output (kW)", color="b")
    ax1.tick_params(axis="y", labelcolor="b")

    ax2 = ax1.twinx()
    ax2.plot(results["volume"], np.array(results["eta_chp"]) * 100,
             "g--", linewidth=1.5, alpha=0.7, label="CHP Efficiency")
    ax2.set_ylabel("CHP Efficiency (%)", color="g")
    ax2.tick_params(axis="y", labelcolor="g")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="lower right")

    ax1.set_title("Figure 1: Net Electrical Output and CHP Efficiency vs. Reactor Volume")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "fig1_volume_sweep.png", bbox_inches="tight")
    fig.savefig(OUTPUT_DIR / "fig1_volume_sweep.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_boiler_pressure_sweep(results: dict):
    """Plot electrical output and efficiency vs boiler pressure."""
    fig, ax1 = plt.subplots()

    ax1.plot(results["p_boiler_mpa"], results["W_net_elec_kw"],
             "b-o", linewidth=2, markersize=3, label="Net Electrical Output")
    ax1.set_xlabel("Boiler Pressure (MPa)")
    ax1.set_ylabel("Net Electrical Output (kW)", color="b")
    ax1.tick_params(axis="y", labelcolor="b")

    ax2 = ax1.twinx()
    ax2.plot(results["p_boiler_mpa"],
             np.array(results["eta_electrical"]) * 100,
             "r--", linewidth=1.5, label="Electrical Efficiency")
    ax2.set_ylabel("Electrical Efficiency (%)", color="r")
    ax2.tick_params(axis="y", labelcolor="r")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="lower right")

    ax1.set_title("Figure 2: Effect of Boiler Pressure on CHP Performance")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "fig2_boiler_pressure.png", bbox_inches="tight")
    fig.savefig(OUTPUT_DIR / "fig2_boiler_pressure.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_extraction_pressure_sweep(results: dict):
    """Plot performance vs extraction pressure."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    ax1.plot(results["p_extract_kpa"], results["W_net_elec_kw"],
             "b-", linewidth=2, label="Electrical Output")
    ax1.plot(results["p_extract_kpa"], results["Q_process_kw"],
             "r--", linewidth=2, label="Process Heat")
    ax1.set_xlabel("Extraction Pressure (kPa)")
    ax1.set_ylabel("Power / Heat (kW)")
    ax1.legend()
    ax1.set_title("(a) Power and Heat vs. Extraction Pressure")

    ax2.plot(results["p_extract_kpa"],
             np.array(results["eta_electrical"]) * 100,
             "b-", linewidth=2, label="Electrical Eff.")
    ax2.plot(results["p_extract_kpa"],
             np.array(results["eta_chp"]) * 100,
             "g--", linewidth=2, label="CHP Eff.")
    ax2.set_xlabel("Extraction Pressure (kPa)")
    ax2.set_ylabel("Efficiency (%)")
    ax2.legend()
    ax2.set_title("(b) Efficiencies vs. Extraction Pressure")

    fig.suptitle("Figure 3: Effect of Extraction Pressure on System Performance",
                 fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "fig3_extraction_pressure.png", bbox_inches="tight")
    fig.savefig(OUTPUT_DIR / "fig3_extraction_pressure.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_energy_balance(dig_out: DigesterOutput, chp_out: CHPOutput):
    """Stacked bar chart showing energy flows through the system."""
    fig, ax = plt.subplots(figsize=(10, 6))

    categories = ["Biogas\nEnergy", "Steam\n(after boiler)", "Useful\nOutputs", "Losses"]

    # Biogas energy breakdown
    biogas_kw = dig_out.thermal_energy_biogas
    boiler_loss = biogas_kw * (1 - chp_out.states[6].p / chp_out.states[6].p)  # placeholder
    boiler_loss = biogas_kw - chp_out.Q_boiler  # Actual boiler loss

    # Bar 1: Biogas total
    ax.bar(0, biogas_kw, color="#2196F3", edgecolor="black", linewidth=0.5)
    ax.text(0, biogas_kw / 2, f"{biogas_kw:.0f} kW", ha="center", va="center",
            fontsize=10, fontweight="bold", color="white")

    # Bar 2: Steam energy (after boiler efficiency)
    ax.bar(1, chp_out.Q_boiler, color="#4CAF50", edgecolor="black", linewidth=0.5)
    ax.text(1, chp_out.Q_boiler / 2, f"{chp_out.Q_boiler:.0f} kW", ha="center",
            va="center", fontsize=10, fontweight="bold", color="white")

    # Bar 3: Useful outputs (stacked)
    ax.bar(2, chp_out.W_net_electrical, color="#FF9800", edgecolor="black",
           linewidth=0.5, label=f"Electrical: {chp_out.W_net_electrical:.0f} kW")
    ax.bar(2, chp_out.Q_process, bottom=chp_out.W_net_electrical, color="#F44336",
           edgecolor="black", linewidth=0.5,
           label=f"Process Heat: {chp_out.Q_process:.0f} kW")

    # Bar 4: Losses (stacked)
    ax.bar(3, boiler_loss, color="#9E9E9E", edgecolor="black", linewidth=0.5,
           label=f"Boiler Loss: {boiler_loss:.0f} kW")
    ax.bar(3, chp_out.Q_condenser, bottom=boiler_loss, color="#607D8B",
           edgecolor="black", linewidth=0.5,
           label=f"Condenser: {chp_out.Q_condenser:.0f} kW")
    other_loss = biogas_kw - chp_out.W_net_electrical - chp_out.Q_process - boiler_loss - chp_out.Q_condenser
    if other_loss > 0:
        ax.bar(3, other_loss, bottom=boiler_loss + chp_out.Q_condenser,
               color="#BDBDBD", edgecolor="black", linewidth=0.5,
               label=f"Other: {other_loss:.0f} kW")

    ax.set_xticks(range(4))
    ax.set_xticklabels(categories)
    ax.set_ylabel("Energy Rate (kW)")
    ax.set_title("Figure 4: System Energy Balance")
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "fig4_energy_balance.png", bbox_inches="tight")
    fig.savefig(OUTPUT_DIR / "fig4_energy_balance.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_grid_comparison(dig_out: DigesterOutput, chp_out: CHPOutput,
                         wwtp_demand_kw: float):
    """Bar chart comparing CHP system to grid-only operation."""
    fig, axes = plt.subplots(1, 3, figsize=(14, 5))

    # Annual values
    hours_per_year = 8760
    chp_elec_kwh = chp_out.W_net_electrical * hours_per_year
    grid_elec_kwh = wwtp_demand_kw * hours_per_year
    chp_grid_kwh = max(0, grid_elec_kwh - chp_elec_kwh)

    # (a) Annual electricity (MWh)
    ax = axes[0]
    bars = ax.bar(["Grid Only", "With CHP\n(Grid)", "With CHP\n(Self-Gen)"],
                  [grid_elec_kwh / 1000, chp_grid_kwh / 1000, chp_elec_kwh / 1000],
                  color=["#F44336", "#FF9800", "#4CAF50"], edgecolor="black", linewidth=0.5)
    ax.set_ylabel("Annual Electricity (MWh)")
    ax.set_title("(a) Electricity Source")
    for bar in bars:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 20,
                f"{bar.get_height():.0f}", ha="center", va="bottom", fontsize=9)

    # (b) Annual cost ($)
    ax = axes[1]
    grid_cost = grid_elec_kwh * GRID_ELECTRICITY_COST
    chp_cost = chp_grid_kwh * GRID_ELECTRICITY_COST
    savings = grid_cost - chp_cost
    bars = ax.bar(["Grid Only", "With CHP", "Savings"],
                  [grid_cost / 1000, chp_cost / 1000, savings / 1000],
                  color=["#F44336", "#FF9800", "#4CAF50"], edgecolor="black", linewidth=0.5)
    ax.set_ylabel("Annual Cost ($k)")
    ax.set_title("(b) Electricity Cost")
    for bar in bars:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f"${bar.get_height():.0f}k", ha="center", va="bottom", fontsize=9)

    # (c) Annual CO2 emissions (tonnes)
    ax = axes[2]
    grid_co2 = grid_elec_kwh * GRID_CO2_INTENSITY / 1000  # tonnes
    chp_co2 = chp_grid_kwh * GRID_CO2_INTENSITY / 1000
    co2_saved = grid_co2 - chp_co2
    bars = ax.bar(["Grid Only", "With CHP", "Avoided"],
                  [grid_co2, chp_co2, co2_saved],
                  color=["#F44336", "#FF9800", "#4CAF50"], edgecolor="black", linewidth=0.5)
    ax.set_ylabel("Annual CO$_2$ (tonnes)")
    ax.set_title("(c) Carbon Emissions")
    for bar in bars:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 5,
                f"{bar.get_height():.0f}", ha="center", va="bottom", fontsize=9)

    fig.suptitle("Figure 5: CHP System vs. Grid-Only Operation (Annual Basis)",
                 fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "fig5_grid_comparison.png", bbox_inches="tight")
    fig.savefig(OUTPUT_DIR / "fig5_grid_comparison.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_breakeven_vs_population(chp_params: CHPParams):
    """Plot required reactor volume and CHP output vs population served."""
    populations = np.linspace(20000, 300000, 30)
    volumes = []
    w_nets = []
    demands = []

    for pop in populations:
        ww_flow = pop * WASTEWATER_PER_CAPITA  # m3/day
        demand_kw = ww_flow * WWTP_SPECIFIC_ENERGY / 24.0  # kW

        # Binary search for breakeven volume
        v_low, v_high = 100, 30000
        for _ in range(50):
            v_mid = (v_low + v_high) / 2
            dp = DigesterParams(volume=v_mid, feed_flow_rate=v_mid / 20.0)
            _, chp_out = run_simulation(dp, chp_params)
            if chp_out.W_net_electrical < demand_kw:
                v_low = v_mid
            else:
                v_high = v_mid

        volumes.append((v_low + v_high) / 2)
        w_nets.append(demand_kw)
        demands.append(demand_kw)

    fig, ax1 = plt.subplots()
    ax1.plot(populations / 1000, volumes, "b-", linewidth=2,
             label="Required Reactor Volume")
    ax1.set_xlabel("Population Served (thousands)")
    ax1.set_ylabel("Breakeven Reactor Volume (m$^3$)", color="b")
    ax1.tick_params(axis="y", labelcolor="b")

    ax2 = ax1.twinx()
    ax2.plot(populations / 1000, demands, "r--", linewidth=1.5,
             label="WWTP Electricity Demand")
    ax2.set_ylabel("WWTP Demand (kW)", color="r")
    ax2.tick_params(axis="y", labelcolor="r")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

    ax1.set_title("Figure 6: Breakeven Reactor Volume vs. Population Served")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "fig6_breakeven_population.png", bbox_inches="tight")
    fig.savefig(OUTPUT_DIR / "fig6_breakeven_population.pdf", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Efficiency summary table
# ---------------------------------------------------------------------------
def create_efficiency_table(chp_params: CHPParams) -> str:
    """Generate a markdown table of efficiencies at various operating points."""
    scenarios = [
        ("Small (V=1000 m3)", 1000),
        ("Medium (V=3000 m3)", 3000),
        ("Large (V=6000 m3)", 6000),
        ("Very Large (V=10000 m3)", 10000),
    ]

    lines = [
        "| Scenario | Volume (m3) | CH4 (m3/d) | Biogas (kW) | W_elec (kW) | "
        "Q_process (kW) | Heat Demand (kW) | eta_elec (%) | eta_CHP (%) | y |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for name, v in scenarios:
        dp = DigesterParams(volume=v, feed_flow_rate=v / 20.0)
        dig_out, chp_out = run_simulation(dp, chp_params)
        lines.append(
            f"| {name} | {v} | {dig_out.methane_rate:.0f} | "
            f"{dig_out.thermal_energy_biogas:.0f} | "
            f"{chp_out.W_net_electrical:.1f} | {chp_out.Q_process:.1f} | "
            f"{dig_out.heat_demand_total:.1f} | "
            f"{chp_out.eta_electrical * 100:.1f} | "
            f"{chp_out.eta_chp * 100:.1f} | "
            f"{chp_out.extraction_fraction:.3f} |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("ANAEROBIC DIGESTER + COGENERATION PLANT SIMULATION")
    print("ME 401 Thermo III - Project 2")
    print("=" * 70)

    # --- Default parameters ---
    digester_params = DigesterParams()
    chp_params = CHPParams()

    # WWTP demand
    ww_flow = POPULATION_SERVED * WASTEWATER_PER_CAPITA
    wwtp_demand_kw = ww_flow * WWTP_SPECIFIC_ENERGY / 24.0  # kW

    print(f"\nWastewater flow: {ww_flow:.0f} m3/day ({POPULATION_SERVED:,} population)")
    print(f"WWTP electricity demand: {wwtp_demand_kw:.1f} kW")

    # --- 1. Baseline simulation ---
    print("\n--- BASELINE SIMULATION ---")
    dig_out, chp_out = run_simulation(digester_params, chp_params)

    print(f"Reactor volume: {digester_params.volume} m3")
    print(f"Feed rate: {digester_params.feed_flow_rate} m3/day")
    print(f"HRT: {dig_out.hrt:.1f} days")
    print(f"OLR: {dig_out.olr:.2f} kg VS/(m3*day)")
    print(f"Methane production: {dig_out.methane_rate:.1f} m3/day")
    print(f"Biogas energy: {dig_out.thermal_energy_biogas:.1f} kW")
    print(f"Digester heat demand: {dig_out.heat_demand_total:.1f} kW")
    print(f"  - Sludge heating: {dig_out.heat_demand_sludge:.1f} kW")
    print(f"  - Wall losses: {dig_out.heat_demand_losses:.1f} kW")

    chp_plant = CogenerationPlant(chp_params)
    print(f"\n{chp_plant.state_table(chp_out)}")

    print(f"\nSteam mass flow: {chp_out.steam_mass_flow:.3f} kg/s")
    print(f"Extraction fraction (y): {chp_out.extraction_fraction:.4f}")
    print(f"Turbine power: {chp_out.W_turbine:.1f} kW")
    print(f"Pump power: {chp_out.W_pumps:.1f} kW")
    print(f"Net mechanical: {chp_out.W_net_mechanical:.1f} kW")
    print(f"Net electrical: {chp_out.W_net_electrical:.1f} kW")
    print(f"Process heat delivered: {chp_out.Q_process:.1f} kW")
    print(f"Condenser heat rejected: {chp_out.Q_condenser:.1f} kW")
    print(f"Electrical efficiency: {chp_out.eta_electrical * 100:.1f}%")
    print(f"Thermal efficiency: {chp_out.eta_thermal * 100:.1f}%")
    print(f"CHP efficiency: {chp_out.eta_chp * 100:.1f}%")
    print(f"Grid offset: {chp_out.W_net_electrical / wwtp_demand_kw * 100:.1f}%")

    # --- 2. Parametric sweeps ---
    print("\n--- PARAMETRIC SWEEPS ---")

    print("  Running reactor volume sweep...")
    vol_results = sweep_reactor_volume(chp_params)
    plot_volume_sweep(vol_results, wwtp_demand_kw)

    print("  Running boiler pressure sweep...")
    bp_results = sweep_boiler_pressure(digester_params)
    plot_boiler_pressure_sweep(bp_results)

    print("  Running extraction pressure sweep...")
    ep_results = sweep_extraction_pressure(digester_params, chp_params)
    plot_extraction_pressure_sweep(ep_results)

    print("  Plotting energy balance...")
    plot_energy_balance(dig_out, chp_out)

    print("  Plotting grid comparison...")
    plot_grid_comparison(dig_out, chp_out, wwtp_demand_kw)

    print("  Plotting breakeven vs population...")
    plot_breakeven_vs_population(chp_params)

    # --- 3. Optimization ---
    print("\n--- OPTIMIZATION ---")

    print("  Optimizing for self-sufficiency...")
    ss_result = optimize_for_self_sufficiency(chp_params, wwtp_demand_kw)
    print(f"    Breakeven volume: {ss_result['optimal_volume_m3']:.0f} m3")
    print(f"    Feed rate: {ss_result['optimal_feed_rate_m3_day']:.0f} m3/day")
    print(f"    W_net: {ss_result['W_net_electrical_kw']:.1f} kW (demand: {wwtp_demand_kw:.1f} kW)")

    print("  Optimizing for max power (V=3000 m3)...")
    mp_result = optimize_max_power(chp_params, volume=3000.0)
    print(f"    Optimal: P_boiler={mp_result['optimal_p_boiler_mpa']:.2f} MPa, "
          f"T_sh={mp_result['optimal_t_superheat_c']:.0f} C, "
          f"P_ext={mp_result['optimal_p_extract_kpa']:.0f} kPa")
    print(f"    W_net: {mp_result['W_net_electrical_kw']:.1f} kW, "
          f"eta_CHP: {mp_result['eta_chp'] * 100:.1f}%")

    print("  Optimizing for max CHP efficiency (V=3000 m3)...")
    me_result = optimize_max_efficiency(chp_params, volume=3000.0)
    print(f"    Optimal: P_boiler={me_result['optimal_p_boiler_mpa']:.2f} MPa, "
          f"T_sh={me_result['optimal_t_superheat_c']:.0f} C, "
          f"P_ext={me_result['optimal_p_extract_kpa']:.0f} kPa")
    print(f"    eta_CHP: {me_result['eta_chp'] * 100:.1f}%")

    # --- 4. Efficiency table ---
    print("\n--- EFFICIENCY TABLE ---")
    table = create_efficiency_table(chp_params)
    print(table)

    # --- 5. Economic analysis ---
    print("\n--- ECONOMIC ANALYSIS ---")
    hours_per_year = 8760
    annual_elec_kwh = chp_out.W_net_electrical * hours_per_year
    annual_savings = annual_elec_kwh * GRID_ELECTRICITY_COST
    capital_cost = chp_out.W_net_electrical * CHP_CAPITAL_COST_PER_KW
    payback_years = capital_cost / annual_savings if annual_savings > 0 else float("inf")
    annual_co2_avoided = annual_elec_kwh * GRID_CO2_INTENSITY / 1000  # tonnes

    print(f"Annual electricity generated: {annual_elec_kwh:.0f} kWh ({annual_elec_kwh/1000:.0f} MWh)")
    print(f"Annual cost savings: ${annual_savings:,.0f}")
    print(f"Estimated capital cost: ${capital_cost:,.0f}")
    print(f"Simple payback period: {payback_years:.1f} years")
    print(f"Annual CO2 avoided: {annual_co2_avoided:.0f} tonnes")

    # --- 6. Save results to JSON ---
    output_data = {
        "simulation_parameters": {
            "population_served": POPULATION_SERVED,
            "wastewater_flow_m3_day": ww_flow,
            "wwtp_demand_kw": wwtp_demand_kw,
            "grid_electricity_cost_per_kwh": GRID_ELECTRICITY_COST,
            "grid_co2_intensity_kg_per_kwh": GRID_CO2_INTENSITY,
        },
        "digester": {
            "volume_m3": digester_params.volume,
            "feed_rate_m3_day": digester_params.feed_flow_rate,
            "temperature_c": digester_params.temperature,
            "hrt_days": dig_out.hrt,
            "olr_kgVS_per_m3_day": dig_out.olr,
            "methane_rate_m3_day": dig_out.methane_rate,
            "biogas_rate_m3_day": dig_out.biogas_rate,
            "biogas_energy_kw": dig_out.thermal_energy_biogas,
            "heat_demand_total_kw": dig_out.heat_demand_total,
            "heat_demand_sludge_kw": dig_out.heat_demand_sludge,
            "heat_demand_losses_kw": dig_out.heat_demand_losses,
            "cod_removed_kg_day": dig_out.cod_removed,
        },
        "cogeneration": {
            "p_boiler_mpa": chp_params.p_boiler / 1e6,
            "t_superheat_c": chp_params.t_superheat,
            "p_extract_kpa": chp_params.p_extract / 1e3,
            "p_condenser_kpa": chp_params.p_condenser / 1e3,
            "eta_turbine": chp_params.eta_turbine,
            "eta_pump": chp_params.eta_pump,
            "eta_boiler": chp_params.eta_boiler,
            "steam_mass_flow_kg_s": chp_out.steam_mass_flow,
            "extraction_fraction": chp_out.extraction_fraction,
            "W_turbine_kw": chp_out.W_turbine,
            "W_pumps_kw": chp_out.W_pumps,
            "W_net_electrical_kw": chp_out.W_net_electrical,
            "Q_process_kw": chp_out.Q_process,
            "Q_condenser_kw": chp_out.Q_condenser,
            "eta_electrical_pct": chp_out.eta_electrical * 100,
            "eta_thermal_pct": chp_out.eta_thermal * 100,
            "eta_chp_pct": chp_out.eta_chp * 100,
        },
        "grid_comparison": {
            "grid_offset_pct": chp_out.W_net_electrical / wwtp_demand_kw * 100,
            "annual_electricity_generated_kwh": annual_elec_kwh,
            "annual_cost_savings_usd": annual_savings,
            "annual_co2_avoided_tonnes": annual_co2_avoided,
            "estimated_capital_cost_usd": capital_cost,
            "simple_payback_years": payback_years,
        },
        "optimization": {
            "self_sufficiency": ss_result,
            "max_power": mp_result,
            "max_efficiency": me_result,
        },
    }

    json_path = OUTPUT_DIR / "simulation_results.json"
    with open(json_path, "w") as f:
        json.dump(output_data, f, indent=2, default=str)
    print(f"\nResults saved to {json_path}")

    print(f"\nAll plots saved to {OUTPUT_DIR}/")
    print("\n" + "=" * 70)
    print("SIMULATION COMPLETE")
    print("=" * 70)

    return output_data


if __name__ == "__main__":
    main()
