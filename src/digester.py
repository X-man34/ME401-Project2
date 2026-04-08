"""
Anaerobic Digester Model for Wastewater Sludge Treatment.

Models a continuous stirred-tank reactor (CSTR) operating under mesophilic
or thermophilic conditions. Computes biogas/methane production, energy content,
and thermal demand for digester heating.

Key references:
    - Nathia-Neves et al. (2018), "Anaerobic digestion process: technological
      aspects and recent developments"
    - Baseline methane production rate: 0.4 m3 CH4 / m3 reactor / day
    - Baseline VFA concentration: 4.0 g COD/L
"""

import math
from dataclasses import dataclass, field


# --- Physical constants and default parameters ---

LHV_CH4 = 35.8  # Lower heating value of methane, MJ/Nm3 at STP
RHO_SLUDGE = 1020.0  # Density of wastewater sludge, kg/m3
CP_SLUDGE = 4.18  # Specific heat of sludge (approx. water), kJ/(kg*K)
U_WALL = 1.0  # Overall heat transfer coefficient for insulated digester, W/(m2*K)
BIOGAS_CH4_FRACTION = 0.60  # 60% CH4 in biogas (mid-range of 55-70%)
BIOGAS_CO2_FRACTION = 0.40  # 40% CO2


@dataclass
class DigesterParams:
    """Configuration parameters for the anaerobic digester."""

    # Reactor geometry
    volume: float = 3000.0  # Reactor volume, m3
    height_to_diameter_ratio: float = 1.5  # H/D ratio for cylindrical tank

    # Feed characteristics
    feed_flow_rate: float = 150.0  # Sludge feed rate, m3/day
    cod_in: float = 40.0  # Influent COD concentration, g/L (kg/m3)
    vs_in: float = 25.0  # Influent volatile solids, kg/m3
    vfa_concentration: float = 4.0  # Steady-state VFA in reactor, g COD/L

    # Operating conditions
    temperature: float = 35.0  # Operating temperature, deg C (mesophilic)
    feed_temperature: float = 15.0  # Incoming sludge temperature, deg C
    ambient_temperature: float = 20.0  # Ambient for heat loss calc, deg C

    # Kinetic parameters
    methane_production_rate: float = 0.4  # Volumetric CH4 rate, m3 CH4/(m3 reactor * day)
    cod_removal_efficiency: float = 0.70  # Fraction of COD removed
    vs_destruction_efficiency: float = 0.55  # Fraction of VS destroyed

    # Biogas composition
    ch4_fraction: float = BIOGAS_CH4_FRACTION
    co2_fraction: float = BIOGAS_CO2_FRACTION


@dataclass
class DigesterOutput:
    """Results from a single digester evaluation."""

    # Operational parameters
    hrt: float = 0.0  # Hydraulic retention time, days
    olr: float = 0.0  # Organic loading rate, kg VS/(m3*day)

    # Gas production
    methane_rate: float = 0.0  # Methane production, m3/day
    biogas_rate: float = 0.0  # Total biogas production, m3/day

    # Energy
    thermal_energy_biogas: float = 0.0  # Energy content of biogas, kW
    heat_demand_sludge: float = 0.0  # Heat to warm incoming sludge, kW
    heat_demand_losses: float = 0.0  # Heat losses through walls, kW
    heat_demand_total: float = 0.0  # Total digester heating demand, kW

    # Mass balance
    cod_removed: float = 0.0  # COD removed, kg/day
    vs_destroyed: float = 0.0  # VS destroyed, kg/day
    digestate_flow: float = 0.0  # Effluent flow rate, m3/day


class AnaerobicDigester:
    """
    Continuous stirred-tank reactor (CSTR) anaerobic digester model.

    Models steady-state methane and biogas production from wastewater sludge,
    along with the thermal energy balance (heating demand vs biogas energy).
    """

    def __init__(self, params: DigesterParams | None = None):
        self.params = params or DigesterParams()

    def evaluate(self, params: DigesterParams | None = None) -> DigesterOutput:
        """
        Evaluate the digester at steady state.

        Args:
            params: Optional override parameters. Uses self.params if None.

        Returns:
            DigesterOutput with all computed quantities.
        """
        p = params or self.params
        out = DigesterOutput()

        # --- Hydraulic retention time and organic loading rate ---
        out.hrt = p.volume / p.feed_flow_rate  # days
        out.olr = p.feed_flow_rate * p.vs_in / p.volume  # kg VS/(m3*day)

        # --- Methane and biogas production ---
        out.methane_rate = p.methane_production_rate * p.volume  # m3 CH4/day
        out.biogas_rate = out.methane_rate / p.ch4_fraction  # m3 biogas/day

        # --- Energy content of biogas ---
        # Convert m3 CH4/day to kW:  m3/day * MJ/m3 * (1 day/86400 s) * (1000 kJ/MJ) = kW
        out.thermal_energy_biogas = (
            out.methane_rate * LHV_CH4 * 1000.0 / 86400.0
        )  # kW

        # --- Heat demand: warming incoming sludge ---
        # Q = m_dot * cp * dT
        # m_dot in kg/s = Q_feed(m3/day) * rho(kg/m3) / 86400(s/day)
        mass_flow = p.feed_flow_rate * RHO_SLUDGE / 86400.0  # kg/s
        delta_t_sludge = p.temperature - p.feed_temperature  # K
        out.heat_demand_sludge = mass_flow * CP_SLUDGE * delta_t_sludge  # kW

        # --- Heat losses through reactor walls ---
        # Cylindrical reactor: V = pi/4 * D^2 * H, H = ratio * D
        diameter = (4.0 * p.volume / (math.pi * p.height_to_diameter_ratio)) ** (
            1.0 / 3.0
        )
        height = p.height_to_diameter_ratio * diameter
        # Surface area: lateral + top + bottom
        surface_area = (
            math.pi * diameter * height + 2.0 * math.pi * (diameter / 2.0) ** 2
        )
        delta_t_wall = p.temperature - p.ambient_temperature  # K
        out.heat_demand_losses = (
            U_WALL * surface_area * delta_t_wall / 1000.0
        )  # kW (U is W/m2K)

        out.heat_demand_total = out.heat_demand_sludge + out.heat_demand_losses

        # --- Mass balance ---
        out.cod_removed = (
            p.feed_flow_rate * p.cod_in * p.cod_removal_efficiency
        )  # kg/day
        out.vs_destroyed = (
            p.feed_flow_rate * p.vs_in * p.vs_destruction_efficiency
        )  # kg/day
        out.digestate_flow = p.feed_flow_rate  # Continuous process, same volumetric flow

        return out

    def reactor_geometry(self) -> dict:
        """Return reactor dimensions for the current volume."""
        p = self.params
        diameter = (4.0 * p.volume / (math.pi * p.height_to_diameter_ratio)) ** (
            1.0 / 3.0
        )
        height = p.height_to_diameter_ratio * diameter
        surface_area = (
            math.pi * diameter * height + 2.0 * math.pi * (diameter / 2.0) ** 2
        )
        return {
            "diameter_m": diameter,
            "height_m": height,
            "surface_area_m2": surface_area,
            "volume_m3": p.volume,
        }
