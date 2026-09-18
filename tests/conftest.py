import pytest


def make_request(notes, **battery_overrides):
    # Evening-peak tariff, midday solar: a realistic shape with room to arbitrage.
    tariff = [6] * 6 + [8] * 11 + [14] * 5 + [8] * 2
    solar = [0] * 7 + [20, 60, 110, 150, 170, 180, 170, 140, 100, 50, 10] + [0] * 7
    demand = [120] * 6 + [150] * 3 + [200] * 8 + [260] * 5 + [160] * 2
    battery = {
        "capacity_kwh": 400, "initial_energy_kwh": 150, "minimum_energy_kwh": 40,
        "max_charge_kwh_per_hour": 100, "max_discharge_kwh_per_hour": 100,
    }
    battery.update(battery_overrides)
    return {
        "scenario_id": "TEST-1",
        "operator_notes": notes,
        "hours": [{"hour": h, "demand_kwh": demand[h], "solar_kwh": solar[h], "tariff_bdt_per_kwh": tariff[h]}
                  for h in range(24)],
        "battery": battery,
    }


@pytest.fixture
def request_factory():
    return make_request
