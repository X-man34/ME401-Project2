"""Unit tests for the cogeneration (CHP) Rankine cycle model."""

import sys
from pathlib import Path

import pytest
from CoolProp.CoolProp import PropsSI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cogeneration import CogenerationPlant, CHPParams, CHPOutput, StatePoint


class TestStatePoints:
    """Verify thermodynamic state points are physically consistent."""

    @pytest.fixture
    def default_states(self):
        plant = CogenerationPlant()
        return plant.compute_states()

    def test_state1_is_saturated_liquid(self, default_states):
        st = default_states[1]
        assert st.x == pytest.approx(0.0, abs=1e-3)
        assert st.p == pytest.approx(10e3, rel=1e-6)

    def test_state3_is_saturated_liquid(self, default_states):
        st = default_states[3]
        assert st.x == pytest.approx(0.0, abs=1e-3)
        assert st.p == pytest.approx(0.5e6, rel=1e-6)

    def test_state6_is_superheated(self, default_states):
        st = default_states[6]
        t_sat = PropsSI("T", "P", 6e6, "Q", 1, "Water")
        assert st.t > t_sat  # Superheated

    def test_pressures_are_correct(self, default_states):
        params = CHPParams()
        assert default_states[1].p == pytest.approx(params.p_condenser, rel=1e-6)
        assert default_states[2].p == pytest.approx(params.p_extract, rel=1e-6)
        assert default_states[3].p == pytest.approx(params.p_extract, rel=1e-6)
        assert default_states[6].p == pytest.approx(params.p_boiler, rel=1e-6)
        assert default_states[7].p == pytest.approx(params.p_extract, rel=1e-6)
        assert default_states[8].p == pytest.approx(params.p_condenser, rel=1e-6)

    def test_pump1_increases_enthalpy(self, default_states):
        assert default_states[2].h > default_states[1].h

    def test_turbine_decreases_enthalpy(self, default_states):
        assert default_states[7].h < default_states[6].h
        assert default_states[8].h < default_states[7].h

    def test_boiler_exit_temp(self, default_states):
        assert default_states[6].t == pytest.approx(450 + 273.15, rel=1e-3)


class TestIsentropicEfficiency:
    """Verify isentropic efficiency is applied correctly."""

    def test_turbine_efficiency(self):
        params = CHPParams(eta_turbine=0.85)
        plant = CogenerationPlant(params)
        states = plant.compute_states()

        h6 = states[6].h
        s6 = states[6].s
        h7 = states[7].h

        # Isentropic enthalpy at extraction
        h7s = PropsSI("H", "P", params.p_extract, "S", s6, "Water")
        h7_calc = h6 - 0.85 * (h6 - h7s)
        assert h7 == pytest.approx(h7_calc, rel=1e-6)

    def test_pump_efficiency(self):
        params = CHPParams(eta_pump=0.80)
        plant = CogenerationPlant(params)
        states = plant.compute_states()

        h1 = states[1].h
        s1 = states[1].s
        h2 = states[2].h

        h2s = PropsSI("H", "P", params.p_extract, "S", s1, "Water")
        h2_calc = h1 + (h2s - h1) / 0.80
        assert h2 == pytest.approx(h2_calc, rel=1e-6)

    def test_ideal_turbine_gives_more_work(self):
        real = CogenerationPlant(CHPParams(eta_turbine=0.85))
        ideal = CogenerationPlant(CHPParams(eta_turbine=1.0))
        rs = real.compute_states()
        ids = ideal.compute_states()

        # Ideal turbine extracts more enthalpy
        real_work = rs[6].h - rs[7].h
        ideal_work = ids[6].h - ids[7].h
        assert ideal_work > real_work


class TestEvaluate:
    """Test the full CHP evaluation with coupled energy balance."""

    @pytest.fixture
    def baseline_output(self):
        plant = CogenerationPlant()
        return plant.evaluate(Q_fuel_kw=500.0, Q_process_demand_kw=100.0)

    def test_extraction_fraction_in_range(self, baseline_output):
        assert 0.0 <= baseline_output.extraction_fraction <= 1.0

    def test_net_electrical_positive(self, baseline_output):
        assert baseline_output.W_net_electrical > 0

    def test_net_less_than_fuel(self, baseline_output):
        assert baseline_output.W_net_electrical < baseline_output.Q_fuel

    def test_energy_balance_closure(self, baseline_output):
        """First law: Q_fuel = W_net + Q_process + Q_condenser + losses."""
        out = baseline_output
        # Energy in = Q_fuel
        # Energy out = W_net_mech + Q_process + Q_condenser + boiler_loss
        boiler_loss = out.Q_fuel - out.Q_boiler
        energy_out = out.W_net_mechanical + out.Q_process + out.Q_condenser + boiler_loss
        assert energy_out == pytest.approx(out.Q_fuel, rel=0.02)

    def test_chp_efficiency_less_than_one(self, baseline_output):
        assert baseline_output.eta_chp < 1.0
        assert baseline_output.eta_chp > 0.0

    def test_electrical_efficiency_reasonable(self, baseline_output):
        # For a steam Rankine CHP, electrical efficiency typically 15-35%
        assert 0.10 < baseline_output.eta_electrical < 0.40

    def test_process_heat_meets_demand(self, baseline_output):
        # Process heat should approximately match demand
        assert baseline_output.Q_process == pytest.approx(100.0, rel=0.05)

    def test_zero_process_demand(self):
        plant = CogenerationPlant()
        out = plant.evaluate(Q_fuel_kw=500.0, Q_process_demand_kw=0.0)
        assert out.extraction_fraction == pytest.approx(0.0, abs=1e-6)
        assert out.Q_process == pytest.approx(0.0, abs=0.1)

    def test_zero_fuel(self):
        plant = CogenerationPlant()
        out = plant.evaluate(Q_fuel_kw=0.0, Q_process_demand_kw=0.0)
        assert out.W_net_electrical == pytest.approx(0.0, abs=1e-6)
        assert out.eta_chp == 0.0


class TestEfficiencies:
    """Test efficiency calculations."""

    def test_electrical_efficiency_definition(self):
        plant = CogenerationPlant()
        out = plant.evaluate(Q_fuel_kw=500.0, Q_process_demand_kw=50.0)
        assert out.eta_electrical == pytest.approx(
            out.W_net_electrical / out.Q_fuel, rel=1e-6
        )

    def test_thermal_efficiency_definition(self):
        plant = CogenerationPlant()
        out = plant.evaluate(Q_fuel_kw=500.0, Q_process_demand_kw=50.0)
        assert out.eta_thermal == pytest.approx(
            out.Q_process / out.Q_fuel, rel=1e-6
        )

    def test_chp_efficiency_definition(self):
        plant = CogenerationPlant()
        out = plant.evaluate(Q_fuel_kw=500.0, Q_process_demand_kw=50.0)
        assert out.eta_chp == pytest.approx(
            (out.W_net_electrical + out.Q_process) / out.Q_fuel, rel=1e-6
        )

    def test_higher_extraction_raises_thermal_eff(self):
        plant = CogenerationPlant()
        out_low = plant.evaluate(Q_fuel_kw=500.0, Q_process_demand_kw=20.0)
        out_high = plant.evaluate(Q_fuel_kw=500.0, Q_process_demand_kw=100.0)
        assert out_high.eta_thermal > out_low.eta_thermal


class TestParameterSensitivity:
    """Test that outputs respond sensibly to parameter changes."""

    def test_higher_boiler_pressure_more_work(self):
        p_low = CHPParams(p_boiler=4e6)
        p_high = CHPParams(p_boiler=8e6)
        plant_low = CogenerationPlant(p_low)
        plant_high = CogenerationPlant(p_high)
        out_low = plant_low.evaluate(500.0, 50.0)
        out_high = plant_high.evaluate(500.0, 50.0)
        assert out_high.W_net_electrical > out_low.W_net_electrical

    def test_higher_superheat_more_work(self):
        p_low = CHPParams(t_superheat=350.0)
        p_high = CHPParams(t_superheat=500.0)
        plant_low = CogenerationPlant(p_low)
        plant_high = CogenerationPlant(p_high)
        out_low = plant_low.evaluate(500.0, 50.0)
        out_high = plant_high.evaluate(500.0, 50.0)
        assert out_high.W_net_electrical > out_low.W_net_electrical

    def test_more_fuel_more_power(self):
        plant = CogenerationPlant()
        out1 = plant.evaluate(300.0, 50.0)
        out2 = plant.evaluate(600.0, 50.0)
        assert out2.W_net_electrical > out1.W_net_electrical


class TestStateTable:
    """Test the formatted state table output."""

    def test_table_has_all_states(self):
        plant = CogenerationPlant()
        out = plant.evaluate(500.0, 50.0)
        table = plant.state_table(out)
        for i in range(1, 9):
            assert str(i) in table

    def test_table_is_string(self):
        plant = CogenerationPlant()
        out = plant.evaluate(500.0, 50.0)
        assert isinstance(plant.state_table(out), str)
