"""Unit tests for the anaerobic digester model."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.digester import (
    AnaerobicDigester,
    DigesterParams,
    DigesterOutput,
    LHV_CH4,
    RHO_SLUDGE,
    CP_SLUDGE,
    U_WALL,
)


class TestDigesterParams:
    """Test default parameter values and construction."""

    def test_defaults(self):
        p = DigesterParams()
        assert p.volume == 3000.0
        assert p.feed_flow_rate == 150.0
        assert p.temperature == 35.0
        assert p.methane_production_rate == 0.4
        assert p.ch4_fraction == 0.60

    def test_custom_params(self):
        p = DigesterParams(volume=5000, feed_flow_rate=250)
        assert p.volume == 5000
        assert p.feed_flow_rate == 250


class TestHydraulicRetentionTime:
    """Test HRT calculation: HRT = V / Q."""

    def test_default_hrt(self):
        d = AnaerobicDigester()
        out = d.evaluate()
        assert out.hrt == pytest.approx(3000.0 / 150.0, rel=1e-6)
        assert out.hrt == pytest.approx(20.0, rel=1e-6)

    def test_hrt_scales_with_volume(self):
        d = AnaerobicDigester(DigesterParams(volume=6000, feed_flow_rate=150))
        out = d.evaluate()
        assert out.hrt == pytest.approx(40.0, rel=1e-6)

    def test_hrt_scales_with_flow(self):
        d = AnaerobicDigester(DigesterParams(volume=3000, feed_flow_rate=300))
        out = d.evaluate()
        assert out.hrt == pytest.approx(10.0, rel=1e-6)


class TestOrganicLoadingRate:
    """Test OLR calculation: OLR = Q * VS / V."""

    def test_default_olr(self):
        d = AnaerobicDigester()
        out = d.evaluate()
        expected = 150.0 * 25.0 / 3000.0  # 1.25 kg VS/(m3*day)
        assert out.olr == pytest.approx(expected, rel=1e-6)

    def test_olr_units(self):
        d = AnaerobicDigester(DigesterParams(volume=1000, feed_flow_rate=100, vs_in=20))
        out = d.evaluate()
        assert out.olr == pytest.approx(2.0, rel=1e-6)  # 100*20/1000


class TestMethaneProduction:
    """Test methane and biogas production calculations."""

    def test_methane_rate(self):
        d = AnaerobicDigester()
        out = d.evaluate()
        expected = 0.4 * 3000.0  # 1200 m3/day
        assert out.methane_rate == pytest.approx(expected, rel=1e-6)

    def test_biogas_rate(self):
        d = AnaerobicDigester()
        out = d.evaluate()
        expected = 1200.0 / 0.6  # 2000 m3/day
        assert out.biogas_rate == pytest.approx(expected, rel=1e-6)

    def test_methane_scales_with_volume(self):
        d1 = AnaerobicDigester(DigesterParams(volume=1000, feed_flow_rate=50))
        d2 = AnaerobicDigester(DigesterParams(volume=2000, feed_flow_rate=100))
        assert d2.evaluate().methane_rate == pytest.approx(
            2.0 * d1.evaluate().methane_rate, rel=1e-6
        )


class TestEnergyContent:
    """Test biogas energy content calculation."""

    def test_energy_conversion(self):
        d = AnaerobicDigester()
        out = d.evaluate()
        # 1200 m3/day * 35.8 MJ/m3 * 1000 / 86400 = kW
        expected = 1200.0 * LHV_CH4 * 1000.0 / 86400.0
        assert out.thermal_energy_biogas == pytest.approx(expected, rel=1e-6)

    def test_energy_is_positive(self):
        d = AnaerobicDigester()
        out = d.evaluate()
        assert out.thermal_energy_biogas > 0


class TestHeatDemand:
    """Test digester heating demand calculations."""

    def test_sludge_heating(self):
        p = DigesterParams(
            feed_flow_rate=100.0,
            temperature=35.0,
            feed_temperature=15.0,
        )
        d = AnaerobicDigester(p)
        out = d.evaluate()
        # mass_flow = 100 * 1020 / 86400 kg/s
        mass_flow = 100.0 * RHO_SLUDGE / 86400.0
        expected = mass_flow * CP_SLUDGE * 20.0  # kW
        assert out.heat_demand_sludge == pytest.approx(expected, rel=1e-4)

    def test_no_heating_if_same_temp(self):
        p = DigesterParams(temperature=15.0, feed_temperature=15.0)
        d = AnaerobicDigester(p)
        out = d.evaluate()
        assert out.heat_demand_sludge == pytest.approx(0.0, abs=1e-6)

    def test_wall_losses_positive(self):
        d = AnaerobicDigester()
        out = d.evaluate()
        assert out.heat_demand_losses > 0

    def test_wall_losses_zero_if_same_temp(self):
        p = DigesterParams(temperature=20.0, ambient_temperature=20.0)
        d = AnaerobicDigester(p)
        out = d.evaluate()
        assert out.heat_demand_losses == pytest.approx(0.0, abs=1e-6)

    def test_total_heat_is_sum(self):
        d = AnaerobicDigester()
        out = d.evaluate()
        assert out.heat_demand_total == pytest.approx(
            out.heat_demand_sludge + out.heat_demand_losses, rel=1e-6
        )


class TestMassBalance:
    """Test COD and VS removal calculations."""

    def test_cod_removed(self):
        p = DigesterParams(feed_flow_rate=100, cod_in=40, cod_removal_efficiency=0.7)
        d = AnaerobicDigester(p)
        out = d.evaluate()
        assert out.cod_removed == pytest.approx(100 * 40 * 0.7, rel=1e-6)

    def test_vs_destroyed(self):
        p = DigesterParams(feed_flow_rate=100, vs_in=25, vs_destruction_efficiency=0.55)
        d = AnaerobicDigester(p)
        out = d.evaluate()
        assert out.vs_destroyed == pytest.approx(100 * 25 * 0.55, rel=1e-6)


class TestReactorGeometry:
    """Test cylindrical reactor geometry calculations."""

    def test_geometry_volume_consistency(self):
        d = AnaerobicDigester(DigesterParams(volume=3000))
        geo = d.reactor_geometry()
        # Verify V = pi/4 * D^2 * H
        v_calc = math.pi / 4 * geo["diameter_m"] ** 2 * geo["height_m"]
        assert v_calc == pytest.approx(3000.0, rel=1e-4)

    def test_hd_ratio(self):
        p = DigesterParams(volume=1000, height_to_diameter_ratio=2.0)
        d = AnaerobicDigester(p)
        geo = d.reactor_geometry()
        assert geo["height_m"] / geo["diameter_m"] == pytest.approx(2.0, rel=1e-6)


class TestParameterOverride:
    """Test that evaluate() accepts parameter overrides."""

    def test_override(self):
        d = AnaerobicDigester(DigesterParams(volume=1000))
        override = DigesterParams(volume=2000, feed_flow_rate=100)
        out = d.evaluate(override)
        assert out.hrt == pytest.approx(20.0, rel=1e-6)
        assert out.methane_rate == pytest.approx(800.0, rel=1e-6)
