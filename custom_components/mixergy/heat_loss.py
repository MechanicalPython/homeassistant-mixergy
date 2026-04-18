"""
Mixergy passive heat loss calculator.

Uses Newton's Law of Cooling measured over idle periods:
    P_loss [W] = (m [kg] * c [J/kg/K] * ΔT [K]) / Δt [s]

Idle detection relies on Mixergy's reported charge % — if charge is not
rising (no heating) and no significant draw is occurring (charge not
falling fast), the tank is considered idle.

The calculator is fed one TankSample per coordinator poll.  When a
sufficiently long idle window is found, a HeatLossResult is produced and
appended to a 24-hour rolling buffer.  The rolling_average_watts property
summarises that buffer.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .const import WATER_DENSITY

_LOGGER = logging.getLogger(__name__)

ROLLING_WINDOW_HOURS = 24


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TankSample:
    """One snapshot of tank state from the Mixergy API."""
    timestamp: datetime
    temp_top_c: float
    temp_bottom_c: float
    charge_pct: float


@dataclass
class HeatLossResult:
    """Output of a single heat-loss calculation over an idle window."""
    timestamp: datetime                  # when the result was produced (UTC)
    power_watts: float                   # instantaneous heat loss (W)
    delta_temp_k: float                  # temperature drop over the window (K)
    delta_time_s: float                  # length of the idle window (s)
    ambient_temp_c: Optional[float]      # ambient temperature used (°C), or None
    u_value_w_m2_k: Optional[float]      # effective U-value (W/m²·K), or None


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

class HeatLossCalculator:
    """
    Maintains a rolling buffer of TankSamples and computes passive heat loss
    whenever a valid idle window exists.

    Typical usage
    -------------
    Each time the coordinator fetches data, call::

        calculator.add_sample(TankSample(...))
        result = calculator.calculate(ambient_temp_c=ambient)

    ``result`` is None when there is insufficient idle time or the temperature
    drop is below the noise threshold.
    """

    def __init__(
        self,
        tank_litres: float,
        tank_surface_m2: float,
    ) -> None:
        # Physical properties
        self.tank_mass_kg: float = tank_litres * WATER_DENSITY   # 1 kg per litre
        self.tank_surface_m2: float = tank_surface_m2

        # 120 samples @ 1 min poll = 2 hours of raw history
        self._samples: deque[TankSample] = deque(maxlen=120)

        # 24-hour rolling window of completed results
        self._rolling_results: deque[HeatLossResult] = deque()
        self._last_result: Optional[HeatLossResult] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_sample(self, sample: TankSample) -> None:
        """Ingest a new reading from the Mixergy API.

        Should be called once per coordinator refresh, before calculate().
        """
        self._samples.append(sample)
        self._purge_old_rolling_results()

    def calculate(
        self,
        idle_window_seconds: int = 300,
        min_temp_drop_k: float = 0.1,
        ambient_temp_c: Optional[float] = None,
    ) -> Optional[HeatLossResult]:
        """Attempt to compute heat loss over the most recent idle window.

        Parameters
        ----------
        idle_window_seconds:
            Minimum idle period (no heating / significant draw) required
            before a measurement is accepted.
        min_temp_drop_k:
            Ignore windows where the temperature fell less than this many
            Kelvin — avoids noise when the tank is at near-steady state.
        ambient_temp_c:
            Current ambient/room temperature used to derive the U-value.
            Pass None to skip U-value estimation.

        Returns
        -------
        HeatLossResult if a valid window was found, else None.
        """
        idle_samples = self._find_idle_window(idle_window_seconds)
        if not idle_samples:
            return None

        first, last = idle_samples[0], idle_samples[-1]

        # Use the mean of top and bottom sensors as a proxy for bulk temp
        temp_start = self._mean_temp(first)
        temp_end   = self._mean_temp(last)
        delta_t_k  = temp_start - temp_end       # positive when cooling

        if delta_t_k < min_temp_drop_k:
            _LOGGER.debug("Delta T=%.3f K below threshold — skipping", delta_t_k)
            return None

        delta_time_s = (last.timestamp - first.timestamp).total_seconds()
        if delta_time_s <= 0:
            return None

        # Newton's Law of Cooling:  P = m * c * delta_T / delta_t
        power_w = self.tank_mass_kg * 4186.0 * delta_t_k / delta_time_s

        # Effective U-value:  P = U * A * (T_tank - T_ambient)
        u_value: Optional[float] = None
        if ambient_temp_c is not None:
            mean_tank_temp = (temp_start + temp_end) / 2.0
            delta_ambient  = mean_tank_temp - ambient_temp_c
            if delta_ambient > 0:
                u_value = power_w / (self.tank_surface_m2 * delta_ambient)

        result = HeatLossResult(
            timestamp      = datetime.now(tz=timezone.utc),
            power_watts    = round(power_w, 2),
            delta_temp_k   = round(delta_t_k, 4),
            delta_time_s   = round(delta_time_s, 1),
            ambient_temp_c = ambient_temp_c,
            u_value_w_m2_k = round(u_value, 4) if u_value is not None else None,
        )

        self._last_result = result
        self._rolling_results.append(result)
        _LOGGER.debug(
            "Heat loss: %.1f W  delta_T=%.3f K  delta_t=%.0f s  U=%s W/m2K",
            result.power_watts,
            result.delta_temp_k,
            result.delta_time_s,
            result.u_value_w_m2_k,
        )
        return result

    @property
    def rolling_average_watts(self) -> Optional[float]:
        """Mean heat loss power across all results in the last 24 hours."""
        if not self._rolling_results:
            return None
        total = sum(r.power_watts for r in self._rolling_results)
        return round(total / len(self._rolling_results), 2)

    @property
    def last_result(self) -> Optional[HeatLossResult]:
        """The most recent successfully computed HeatLossResult, or None."""
        return self._last_result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_idle_window(self, min_window_s: int) -> list[TankSample]:
        """Return the most recent contiguous run of samples where tank
        charge % is stable (within 0.5 pp), meaning no significant heating
        or hot-water draw is occurring.

        Iterates backwards through the buffer so we always capture the
        *latest* idle period first.
        """
        if len(self._samples) < 2:
            return []

        idle_run: list[TankSample] = []
        for sample in reversed(self._samples):
            if not idle_run:
                idle_run.append(sample)
                continue

            prev         = idle_run[-1]
            charge_delta = abs(sample.charge_pct - prev.charge_pct)

            if charge_delta > 0.5:       # active heating or significant draw
                break
            idle_run.append(sample)

        if len(idle_run) < 2:
            return []

        idle_run.reverse()               # restore chronological order

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
        """Bulk temperature estimate: average of top and bottom sensors."""
        return (sample.temp_top_c + sample.temp_bottom_c) / 2.0

    def _purge_old_rolling_results(self) -> None:
        """Remove results older than ROLLING_WINDOW_HOURS from the buffer."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=ROLLING_WINDOW_HOURS)
        self._rolling_results = deque(
            r for r in self._rolling_results if r.timestamp >= cutoff
        )