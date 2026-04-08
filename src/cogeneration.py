"""
Steam Rankine Cogeneration (CHP) Plant Model.

Models a combined heat and power system driven by biogas from an anaerobic
digester. Uses a regenerative Rankine cycle with steam extraction for process
heating (digester thermal demand).

Components: boiler, extraction turbine, condenser, two pumps, process heater,
and mixing chamber. Thermodynamic states computed via CoolProp.

Cycle state points:
    1 - Condenser exit (saturated liquid, P_cond)
    2 - Pump I exit (compressed liquid, P_extract)
    3 - Process heater exit (saturated liquid, P_extract)
    4 - Mixing chamber exit (liquid, P_extract)
    5 - Pump II exit (compressed liquid, P_boiler)
    6 - Boiler exit (superheated steam, P_boiler)
    7 - Turbine extraction (steam, P_extract)
    8 - Turbine exhaust (steam, P_cond)
"""

from dataclasses import dataclass, field
from CoolProp.CoolProp import PropsSI


@dataclass
class CHPParams:
    """Configuration for the cogeneration Rankine cycle."""

    # Pressures
    p_boiler: float = 6.0e6  # Boiler pressure, Pa (6 MPa)
    t_superheat: float = 450.0  # Superheat temperature, deg C
    p_extract: float = 0.5e6  # Extraction/process heater pressure, Pa (500 kPa)
    p_condenser: float = 10.0e3  # Condenser pressure, Pa (10 kPa)

    # Component efficiencies
    eta_turbine: float = 0.85  # Isentropic turbine efficiency
    eta_pump: float = 0.80  # Isentropic pump efficiency
    eta_boiler: float = 0.85  # Boiler thermal efficiency (fuel to steam)
    eta_generator: float = 0.95  # Electrical generator efficiency

    # Working fluid
    fluid: str = "Water"


@dataclass
class StatePoint:
    """Thermodynamic state at a single point in the cycle."""

    label: str = ""
    p: float = 0.0  # Pressure, Pa
    t: float = 0.0  # Temperature, K
    h: float = 0.0  # Specific enthalpy, J/kg
    s: float = 0.0  # Specific entropy, J/(kg*K)
    x: float = -1.0  # Quality (-1 = subcooled/superheated)


@dataclass
class CHPOutput:
    """Results from a CHP plant evaluation."""

    # State points
    states: dict = field(default_factory=dict)  # {1: StatePoint, ...}

    # Mass flow
    steam_mass_flow: float = 0.0  # Total steam mass flow, kg/s
    extraction_fraction: float = 0.0  # Fraction y extracted for process heat

    # Specific work/heat (per kg of total steam flow)
    w_turbine_specific: float = 0.0  # J/kg
    w_pump1_specific: float = 0.0  # J/kg
    w_pump2_specific: float = 0.0  # J/kg
    q_boiler_specific: float = 0.0  # J/kg
    q_condenser_specific: float = 0.0  # J/kg
    q_process_specific: float = 0.0  # J/kg

    # Absolute power/heat rates
    W_turbine: float = 0.0  # Turbine shaft power, kW
    W_pumps: float = 0.0  # Total pump power, kW
    W_net_mechanical: float = 0.0  # Net mechanical power, kW
    W_net_electrical: float = 0.0  # Net electrical output, kW
    Q_boiler: float = 0.0  # Heat input to boiler, kW
    Q_condenser: float = 0.0  # Heat rejected in condenser, kW
    Q_process: float = 0.0  # Useful process heat delivered, kW

    # Efficiencies
    eta_electrical: float = 0.0  # W_net_elec / Q_fuel
    eta_thermal: float = 0.0  # Q_process / Q_fuel
    eta_chp: float = 0.0  # (W_net_elec + Q_process) / Q_fuel

    # Energy input
    Q_fuel: float = 0.0  # Biogas fuel energy input, kW


class CogenerationPlant:
    """
    Steam Rankine cycle CHP plant with extraction for process heating.

    Given a biogas energy input (from the digester) and a process heat demand
    (to heat the digester), this class computes all thermodynamic states,
    power output, heat flows, and efficiencies.
    """

    def __init__(self, params: CHPParams | None = None):
        self.params = params or CHPParams()

    def _props(self, output: str, input1: str, val1: float,
               input2: str, val2: float) -> float:
        """Wrapper around CoolProp PropsSI."""
        return PropsSI(output, input1, val1, input2, val2, self.params.fluid)

    def compute_states(self, params: CHPParams | None = None) -> dict[int, StatePoint]:
        """
        Fix all 8 thermodynamic state points in the Rankine cycle.

        Returns:
            Dictionary mapping state number (1-8) to StatePoint.
        """
        p = params or self.params
        states = {}

        # State 1: Condenser exit -- saturated liquid at P_cond
        h1 = self._props("H", "P", p.p_condenser, "Q", 0)
        s1 = self._props("S", "P", p.p_condenser, "Q", 0)
        t1 = self._props("T", "P", p.p_condenser, "Q", 0)
        states[1] = StatePoint("Condenser exit", p.p_condenser, t1, h1, s1, 0.0)

        # State 2: Pump I exit -- isentropic compression to P_extract
        h2s = self._props("H", "P", p.p_extract, "S", s1)
        h2 = h1 + (h2s - h1) / p.eta_pump
        t2 = self._props("T", "P", p.p_extract, "H", h2)
        s2 = self._props("S", "P", p.p_extract, "H", h2)
        states[2] = StatePoint("Pump I exit", p.p_extract, t2, h2, s2)

        # State 3: Process heater exit -- saturated liquid at P_extract
        h3 = self._props("H", "P", p.p_extract, "Q", 0)
        s3 = self._props("S", "P", p.p_extract, "Q", 0)
        t3 = self._props("T", "P", p.p_extract, "Q", 0)
        states[3] = StatePoint("Process heater exit", p.p_extract, t3, h3, s3, 0.0)

        # State 6: Boiler exit -- superheated steam at P_boiler, T_superheat
        t6 = p.t_superheat + 273.15  # Convert to K
        h6 = self._props("H", "P", p.p_boiler, "T", t6)
        s6 = self._props("S", "P", p.p_boiler, "T", t6)
        states[6] = StatePoint("Boiler exit", p.p_boiler, t6, h6, s6)

        # State 7: Turbine extraction -- isentropic expansion to P_extract
        h7s = self._props("H", "P", p.p_extract, "S", s6)
        h7 = h6 - p.eta_turbine * (h6 - h7s)
        t7 = self._props("T", "P", p.p_extract, "H", h7)
        s7 = self._props("S", "P", p.p_extract, "H", h7)
        states[7] = StatePoint("Turbine extraction", p.p_extract, t7, h7, s7)

        # State 8: Turbine exhaust -- expansion from state 7 to P_cond
        h8s = self._props("H", "P", p.p_condenser, "S", s7)
        h8 = h7 - p.eta_turbine * (h7 - h8s)
        t8 = self._props("T", "P", p.p_condenser, "H", h8)
        s8 = self._props("S", "P", p.p_condenser, "H", h8)
        # Check quality at condenser
        h_f = self._props("H", "P", p.p_condenser, "Q", 0)
        h_g = self._props("H", "P", p.p_condenser, "Q", 1)
        x8 = (h8 - h_f) / (h_g - h_f) if h8 < h_g else -1.0
        states[8] = StatePoint("Turbine exhaust", p.p_condenser, t8, h8, s8, x8)

        # States 4 and 5 depend on extraction fraction y, computed in evaluate()
        # Store placeholders
        states[4] = StatePoint("Mixing chamber exit", p.p_extract)
        states[5] = StatePoint("Pump II exit", p.p_boiler)

        return states

    def evaluate(self, Q_fuel_kw: float, Q_process_demand_kw: float,
                 params: CHPParams | None = None) -> CHPOutput:
        """
        Evaluate the CHP plant for given fuel energy and process heat demand.

        Args:
            Q_fuel_kw: Thermal energy input from biogas, kW.
            Q_process_demand_kw: Process heat demand (digester heating), kW.
            params: Optional parameter override.

        Returns:
            CHPOutput with all computed quantities.
        """
        p = params or self.params
        out = CHPOutput()
        out.Q_fuel = Q_fuel_kw

        # Compute fixed state points
        states = self.compute_states(p)

        h1 = states[1].h
        h2 = states[2].h
        h3 = states[3].h
        h6 = states[6].h
        h7 = states[7].h
        h8 = states[8].h

        # Boiler specific heat input
        # First pass: assume y=0 to get initial h4, h5 for q_boiler estimate
        # Then iterate once extraction fraction is known

        # Specific heat available from extraction (per kg extracted)
        q_extract_per_kg = h7 - h3  # J/kg of extracted steam

        # Boiler heat per kg steam (initial estimate using h2 as proxy for h5)
        # We need to solve for y and m_dot simultaneously

        # Total heat input to cycle from fuel
        Q_fuel_to_steam = Q_fuel_kw * 1000.0 * p.eta_boiler  # W (fuel * boiler eff)

        # Iterative solution: y depends on m_dot, m_dot depends on h5, h5 depends on y
        # Start with y = 0
        y = 0.0
        for _ in range(20):  # Converges in a few iterations
            # Mixing chamber: h4 = (1-y)*h2 + y*h3
            h4 = (1.0 - y) * h2 + y * h3

            # Pump II: isentropic compression from P_extract to P_boiler
            s4 = self._props("S", "P", p.p_extract, "H", h4)
            h5s = self._props("H", "P", p.p_boiler, "S", s4)
            h5 = h4 + (h5s - h4) / p.eta_pump

            # Boiler specific heat: q_boiler = h6 - h5
            q_boiler = h6 - h5  # J/kg

            # Steam mass flow rate
            m_dot = Q_fuel_to_steam / q_boiler  # kg/s

            # Required extraction fraction to meet process heat demand
            if q_extract_per_kg > 0 and m_dot > 0:
                y_new = (Q_process_demand_kw * 1000.0) / (m_dot * q_extract_per_kg)
            else:
                y_new = 0.0

            y_new = max(0.0, min(1.0, y_new))  # Clamp to [0, 1]

            if abs(y_new - y) < 1e-8:
                break
            y = y_new

        # Final state points 4 and 5
        h4 = (1.0 - y) * h2 + y * h3
        s4 = self._props("S", "P", p.p_extract, "H", h4)
        t4 = self._props("T", "P", p.p_extract, "H", h4)
        states[4] = StatePoint("Mixing chamber exit", p.p_extract, t4, h4, s4)

        h5s = self._props("H", "P", p.p_boiler, "S", s4)
        h5 = h4 + (h5s - h4) / p.eta_pump
        t5 = self._props("T", "P", p.p_boiler, "H", h5)
        s5 = self._props("S", "P", p.p_boiler, "H", h5)
        states[5] = StatePoint("Pump II exit", p.p_boiler, t5, h5, s5)

        # --- Populate output ---
        out.states = states
        out.steam_mass_flow = m_dot
        out.extraction_fraction = y

        # Specific work/heat per kg total steam
        out.w_turbine_specific = (h6 - h7) + (1.0 - y) * (h7 - h8)
        out.w_pump1_specific = (1.0 - y) * (h2 - h1)
        out.w_pump2_specific = h5 - h4
        out.q_boiler_specific = h6 - h5
        out.q_condenser_specific = (1.0 - y) * (h8 - h1)
        out.q_process_specific = y * (h7 - h3)

        # Absolute power/heat (kW)
        out.W_turbine = m_dot * out.w_turbine_specific / 1000.0
        w_p1 = m_dot * out.w_pump1_specific / 1000.0
        w_p2 = m_dot * out.w_pump2_specific / 1000.0
        out.W_pumps = w_p1 + w_p2
        out.W_net_mechanical = out.W_turbine - out.W_pumps
        out.W_net_electrical = out.W_net_mechanical * p.eta_generator
        out.Q_boiler = m_dot * out.q_boiler_specific / 1000.0
        out.Q_condenser = m_dot * out.q_condenser_specific / 1000.0
        out.Q_process = m_dot * out.q_process_specific / 1000.0

        # Fuel energy input (already stored)
        out.Q_fuel = Q_fuel_kw

        # Efficiencies (relative to fuel input, not steam input)
        if Q_fuel_kw > 0:
            out.eta_electrical = out.W_net_electrical / Q_fuel_kw
            out.eta_thermal = out.Q_process / Q_fuel_kw
            out.eta_chp = (out.W_net_electrical + out.Q_process) / Q_fuel_kw
        else:
            out.eta_electrical = 0.0
            out.eta_thermal = 0.0
            out.eta_chp = 0.0

        return out

    def state_table(self, output: CHPOutput) -> str:
        """Format state points as a readable table."""
        lines = [
            f"{'State':<6} {'Location':<24} {'P (kPa)':>10} {'T (C)':>10} "
            f"{'h (kJ/kg)':>12} {'s (kJ/kgK)':>12} {'x':>6}"
        ]
        lines.append("-" * 82)
        for i in sorted(output.states.keys()):
            st = output.states[i]
            x_str = f"{st.x:.3f}" if st.x >= 0 else "  --"
            lines.append(
                f"{i:<6} {st.label:<24} {st.p / 1000:>10.1f} "
                f"{st.t - 273.15:>10.2f} {st.h / 1000:>12.2f} "
                f"{st.s / 1000:>12.4f} {x_str:>6}"
            )
        return "\n".join(lines)
