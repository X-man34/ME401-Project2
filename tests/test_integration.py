"""Integration tests for the coupled digester-CHP system."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.digester import AnaerobicDigester, DigesterParams
from src.cogeneration import CogenerationPlant, CHPParams
from src.driver import run_simulation, optimize_for_self_sufficiency


class TestCoupledSimulation:
    """Test the digester -> CHP pipeline."""

    def test_pipeline_runs(self):
        dp = DigesterParams()
        cp = CHPParams()
        dig_out, chp_out = run_simulation(dp, cp)
        assert dig_out.methane_rate > 0
        assert chp_out.W_net_electrical > 0

    def test_process_heat_matches_demand(self):
        """CHP process heat should approximately equal digester heat demand."""
        dp = DigesterParams()
        cp = CHPParams()
        dig_out, chp_out = run_simulation(dp, cp)
        # Should be within 5% of demand
        assert chp_out.Q_process == pytest.approx(
            dig_out.heat_demand_total, rel=0.05
        )

    def test_larger_reactor_more_power(self):
        cp = CHPParams()
        dp1 = DigesterParams(volume=1000, feed_flow_rate=50)
        dp2 = DigesterParams(volume=5000, feed_flow_rate=250)
        _, chp1 = run_simulation(dp1, cp)
        _, chp2 = run_simulation(dp2, cp)
        assert chp2.W_net_electrical > chp1.W_net_electrical

    def test_biogas_energy_drives_chp(self):
        """CHP fuel input should equal digester biogas energy."""
        dp = DigesterParams()
        cp = CHPParams()
        dig_out, chp_out = run_simulation(dp, cp)
        assert chp_out.Q_fuel == pytest.approx(
            dig_out.thermal_energy_biogas, rel=1e-6
        )

    def test_energy_conservation(self):
        """Total energy out <= total energy in (first law)."""
        dp = DigesterParams()
        cp = CHPParams()
        dig_out, chp_out = run_simulation(dp, cp)
        energy_in = dig_out.thermal_energy_biogas
        energy_out = (
            chp_out.W_net_mechanical + chp_out.Q_process + chp_out.Q_condenser
            + (energy_in - chp_out.Q_boiler)  # boiler loss
        )
        assert energy_out == pytest.approx(energy_in, rel=0.02)


class TestSelfSufficiencyOptimization:
    """Test the self-sufficiency optimization."""

    def test_optimization_finds_breakeven(self):
        cp = CHPParams()
        wwtp_demand = 250.0  # kW
        result = optimize_for_self_sufficiency(cp, wwtp_demand)
        # Should be close to demand
        assert abs(result["W_net_electrical_kw"] - wwtp_demand) < 10.0

    def test_optimal_volume_is_reasonable(self):
        cp = CHPParams()
        result = optimize_for_self_sufficiency(cp, 250.0)
        # Volume should be between 1000 and 20000 m3
        assert 1000 < result["optimal_volume_m3"] < 20000


class TestScaling:
    """Test that the system scales linearly with reactor volume (at constant HRT)."""

    def test_methane_scales_linearly(self):
        cp = CHPParams()
        volumes = [1000, 2000, 4000]
        ch4_rates = []
        for v in volumes:
            dp = DigesterParams(volume=v, feed_flow_rate=v / 20.0)
            dig_out, _ = run_simulation(dp, cp)
            ch4_rates.append(dig_out.methane_rate)

        # Methane should scale linearly
        assert ch4_rates[1] == pytest.approx(2 * ch4_rates[0], rel=0.01)
        assert ch4_rates[2] == pytest.approx(4 * ch4_rates[0], rel=0.01)

    def test_electrical_output_scales_approximately(self):
        """Electrical output should scale roughly linearly (small nonlinearity from extraction)."""
        cp = CHPParams()
        dp1 = DigesterParams(volume=2000, feed_flow_rate=100)
        dp2 = DigesterParams(volume=4000, feed_flow_rate=200)
        _, chp1 = run_simulation(dp1, cp)
        _, chp2 = run_simulation(dp2, cp)
        ratio = chp2.W_net_electrical / chp1.W_net_electrical
        # Should be approximately 2x (within 15% due to nonlinear heat loss scaling)
        assert 1.7 < ratio < 2.3
