"""HTTP layer: request validation -> interpret -> guardrail -> optimize -> replay -> respond."""
import logging
import math
import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import interpreter
from .directives import build_constraints
from .optimizer import InfeasibleError, solve, to_hourly_plan
from .replay import ReplayError, replay
from .schemas import OptimizeRequest, OptimizeResponse
from .summary import explain, plan_summary

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("gridwise")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(limits=httpx.Limits(max_connections=50))
    yield
    await app.state.http.aclose()


app = FastAPI(title="GridWise", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


@app.exception_handler(RequestValidationError)
async def on_bad_request(request: Request, exc: RequestValidationError):
    problems = []
    for e in exc.errors()[:10]:
        loc = ".".join(str(p) for p in e.get("loc", []) if p != "body")
        problems.append(f"{loc or 'body'}: {e.get('msg', 'invalid')}")
    return error(400, "invalid_request", "; ".join(problems) or "malformed request")


@app.exception_handler(Exception)
async def on_unexpected(request: Request, exc: Exception):
    log.exception("unhandled error")
    return error(500, "internal_error", "internal error")


def physical_problems(req: OptimizeRequest) -> list[str]:
    b = req.battery
    p = []
    numbers = [b.capacity_kwh, b.initial_energy_kwh, b.minimum_energy_kwh, b.max_charge_kwh_per_hour,
               b.max_discharge_kwh_per_hour]
    for h in req.hours:
        numbers += [h.demand_kwh, h.solar_kwh, h.tariff_bdt_per_kwh]
    if not all(math.isfinite(x) for x in numbers):
        return ["all numbers must be finite"]
    if b.capacity_kwh <= 0:
        p.append("capacity_kwh must be positive")
    if b.minimum_energy_kwh < 0 or b.minimum_energy_kwh > b.capacity_kwh:
        p.append("minimum_energy_kwh must be within [0, capacity_kwh]")
    if not b.minimum_energy_kwh <= b.initial_energy_kwh <= b.capacity_kwh:
        p.append("initial_energy_kwh must be within [minimum_energy_kwh, capacity_kwh]")
    if b.max_charge_kwh_per_hour < 0 or b.max_discharge_kwh_per_hour < 0:
        p.append("charge/discharge limits must be non-negative")
    if any(h.demand_kwh < 0 or h.solar_kwh < 0 for h in req.hours):
        p.append("demand_kwh and solar_kwh must be non-negative")
    return p


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeResponse)
async def optimize_energy(req: OptimizeRequest, request: Request):
    started = time.monotonic()
    problems = physical_problems(req)
    if problems:
        return error(422, "invalid_scenario", "; ".join(problems))

    client = request.app.state.http
    solar = [float(h.solar_kwh) for h in req.hours]
    try:
        interp = await interpreter.interpret(client, req.operator_notes, req.battery)
    except interpreter.InterpretationUnavailable as e:
        return error(502, "interpretation_unavailable", str(e))

    cons = build_constraints(interp.directives, solar, req.battery)
    try:
        raw = solve(req.hours, req.battery, cons)
    except InfeasibleError:
        # Organizer scenarios are feasible, so this almost always means a misread note.
        log.warning("%s: infeasible after %s interpretation; re-asking strong model", req.scenario_id, interp.path)
        interpreter.cache.evict(req.operator_notes)
        try:
            interp = await interpreter.interpret(
                client, req.operator_notes, req.battery, force_strong=True,
                feedback="the resulting constraints were physically infeasible together with the battery limits")
            cons = build_constraints(interp.directives, solar, req.battery)
            raw = solve(req.hours, req.battery, cons)
        except (interpreter.InterpretationUnavailable, InfeasibleError):
            interpreter.cache.evict(req.operator_notes)
            return error(422, "infeasible", "no schedule satisfies all interpreted directives and battery limits")

    plan = to_hourly_plan(raw, req.hours, req.battery, cons)
    try:
        totals = replay(plan, req.hours, req.battery, cons)
    except ReplayError as e:
        log.error("%s: replay rejected plan: %s", req.scenario_id, e.violations)
        return error(500, "plan_validation_failed", "generated plan failed final validation")

    log.info("%s: ok path=%s cost=%.4f in %.2fs", req.scenario_id, interp.path, totals.total_cost_bdt,
             time.monotonic() - started)
    return {
        "scenario_id": req.scenario_id,
        "directive_interpretation": [
            {
                "note_index": d.note_index,
                "applies": d.applies,
                "directive_type": d.directive_type,
                "structured_adjustment": d.structured_adjustment(),
                "explanation": explain(d),
            }
            for d in interp.directives
        ],
        "hourly_plan": plan,
        "total_grid_kwh": totals.total_grid_kwh,
        "total_cost_bdt": totals.total_cost_bdt,
        "peak_grid_kwh": totals.peak_grid_kwh,
        "plan_summary": plan_summary(plan, totals, interp.directives),
    }
