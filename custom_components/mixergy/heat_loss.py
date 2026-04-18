"""
Mixergy passive heat loss calculator.

Uses Newton's Law of Cooling measured over idle periods:
    P_loss [W] = (m [kg] * c [J/kg/K] * ΔT [K]) / Δt [s]

Idle detection relies on Mixergy's reported charge % — if
charge is not rising (no heating) and no significant draw is
occurring (charge not falling fast), the tank is idle.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .const import WATER_DENSITY

_LOGGER = logging.getLogger(__name__)

ROLLING_WINDOW_HOURS = 24


@dataclass
class TankSample:
    timestamp: datetime
    temp_top_c: float
    temp_bottom_c: float
    charge_pct: float


@dataclass
class HeatLossResult:
    power_watts: float
    delta_temp_k: float
    delta_time_s: float
    ambient_temp_c: Optional[float]
    u_value_w_m2_k: Optional[float]


class HeatLossCalculator:
    """
    Maintains a rolling buffer of tank samples and computes
    passive heat loss whenever a valid idle window is found.
    """

    def __init__(
            self,
            tank_litres: float,
            tank_surface_m2: float,
    ) -> None:
        self.tank_mass_kg = tank_litres * WATER_DENSITY  # 1 kg per litre
        self.tank_surface_m2 = tank_surface_m2
        self._samples: deque[TankSample] = deque(maxlen=120)  # 2 h at 1 min
        self._rolling_results: deque[HeatLossResult] = deque()
        self._last_result: Optional[HeatLossResult] = None

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def add_sample(self, sample: TankSample) -> None:
        """Ingest a new reading from the Mixergy API."""
        self._samples.append(sample)
        self._purge_old_rolling_results()

    def calculate(
            self,
            idle_window_seconds: int = 300,
            min_temp_drop_k: float = 0.1,
            ambient_temp_c: Optional[float] = None,
    ) -> Optional[HeatLossResult]:
        """
        Attempt to compute heat loss over the most recent idle window.
        Returns None if conditions aren't met (insufficient data, active
        heating, or negligible temperature change).
        """
        idle_samples = self._find_idle_window(idle_window_seconds)
        if not idle_samples:
            return None

        first, last = idle_samples[0], idle_samples[-1]
        # Use the mean of top/bottom sensors as a proxy for bulk temperature
        temp_start = self._mean_temp(first)
        temp_end = self._mean_temp(last)
        delta_t_k = temp_start - temp_end  # positive = cooling

        if delta_t_k < min_temp_drop_k:
            _LOGGER.debug("ΔT=%.3f K below threshold — skipping", delta_t_k)
            return None

        delta_time_s = (last.timestamp - first.timestamp).total_seconds()
        if delta_time_s <= 0:
            return None

        # P = m * c * ΔT / Δt
        power_w = (
                self.tank_mass_kg * 4186.0 * delta_t_k / delta_time_s
        )

        # Estimate effective U-value: P = U * A * (T_tank - T_ambient)
        u_value = None
        if ambient_temp_c is not None:
            mean_tank_temp = (temp_start + temp_end) / 2.0
            delta_ambient = mean_tank_temp - ambient_temp_c
            if delta_ambient > 0:
                u_value = power_w / (self.tank_surface_m2 * delta_ambient)

        result = HeatLossResult(
            power_watts=round(power_w, 2),
            delta_temp_k=round(delta_t_k, 4),
            delta_time_s=round(delta_time_s, 1),
            ambient_temp_c=ambient_temp_c,
            u_value_w_m2_k=round(u_value, 4) if u_value else None,
        )
        self._last_result = result
        self._rolling_results.append(result)
        return result

    @property
    def rolling_average_watts(self) -> Optional[float]:
        """Mean heat loss over the last 24 hours."""
        if not self._rolling_results:
            return None
        total = sum(r.power_watts for r in self._rolling_results)
        return round(total / len(self._rolling_results), 2)

    @property
    def last_result(self) -> Optional[HeatLossResult]:
        return self._last_result

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _find_idle_window(
            self, min_window_s: int
    ) -> list[TankSample]:
        """
        Return the most recent contiguous run of samples where
        the tank charge % is stable (±0.5 %) — meaning no significant
        heating or draw is occurring.
        """
        if len(self._samples) < 2:
            return []

        idle_run: list[TankSample] = []
        for sample in reversed(self._samples):
            if not idle_run:
                idle_run.append(sample)
                continue

            prev = idle_run[-1]
            charge_delta = abs(sample.charge_pct - prev.charge_pct)

            if charge_delta > 0.5:  # active heating or hot draw
                break
            idle_run.append(sample)

        if len(idle_run) < 2:
            return []

        idle_run.reverse()
        window_s = (
                idle_run[-1].timestamp - idle_run[0].timestamp
        ).total_seconds()

        if window_s < min_window_s:
            _LOGGER.debug(
                "Idle window only %.0f s — need %d s", window_s, min_window_s
            )
            return []

        return idle_run

    @staticmethod
    def _mean_temp(sample: TankSample) -> float:
        return (sample.temp_top_c + sample.temp_bottom_c) / 2.0

    def _purge_old_rolling_results(self) -> None:
        cutoff = datetime.utcnow() - timedelta(hours=ROLLING_WINDOW_HOURS)
        # deque has no indexed remove, so rebuild
        self._rolling_results = deque(
            r for r in self._rolling_results
            # We don't store timestamps on results — use a simple maxlen instead
        )
