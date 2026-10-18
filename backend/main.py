from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import tempfile
import threading
from typing import Any, Literal
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

if __package__:
    from .auth.authorization import (
        AUDIT_ROLES,
        REQUESTER_ROLES,
        REVIEWER_ROLES,
        WAREHOUSE_ROLES,
        Principal,
        Role,
        require_roles,
    )
    from .schemas.approval import ApprovalBody
    from .schemas.alert import AlertAcknowledgementBody, HazardEventInput, HazardValidationBody
    from .schemas.allocation import AllocationScenario, AllocationSimulation
    from .schemas.inventory import InventoryReconciliationBody, ReasonBody, StockAdjustmentBody
    from .schemas.scenario import ScenarioInput, ScenarioResult
    from .schemas.requests import CreateRequestBody
    from .services.approval_service import ApprovalError, review_allocation
    from .services.alert_service import (
        AlertError,
        acknowledge_alert,
        ingest_hazard_event,
        list_active_alerts,
        validate_hazard_event,
    )
    from .services.audit_service import append_event, event_hash, verify_chain
    from .services.digital_twin_service import simulate_digital_twin
    from .services.inventory_service import (
        InventoryError,
        adjust_stock,
        append_inventory_movement,
        inventory_snapshot,
        reconcile_inventory,
        release_unused_reservation,
    )
    from .services.resource_allocator import simulate_allocation
else:
    from auth.authorization import (
        AUDIT_ROLES,
        REQUESTER_ROLES,
        REVIEWER_ROLES,
        WAREHOUSE_ROLES,
        Principal,
        Role,
        require_roles,
    )
    from schemas.approval import ApprovalBody
    from schemas.alert import AlertAcknowledgementBody, HazardEventInput, HazardValidationBody
    from schemas.allocation import AllocationScenario, AllocationSimulation
    from schemas.inventory import InventoryReconciliationBody, ReasonBody, StockAdjustmentBody
    from schemas.scenario import ScenarioInput, ScenarioResult
    from schemas.requests import CreateRequestBody
    from services.approval_service import ApprovalError, review_allocation
    from services.alert_service import (
        AlertError,
        acknowledge_alert,
        ingest_hazard_event,
        list_active_alerts,
        validate_hazard_event,
    )
    from services.audit_service import append_event, event_hash, verify_chain
    from services.digital_twin_service import simulate_digital_twin
    from services.inventory_service import (
        InventoryError,
        adjust_stock,
        append_inventory_movement,
        inventory_snapshot,
        reconcile_inventory,
        release_unused_reservation,
    )
    from services.resource_allocator import simulate_allocation

APP_DIR = Path(__file__).resolve().parent
STATE_FILE = APP_DIR / "demo_state.json"
STATE_LOCK_FILE = APP_DIR / "demo_state.lock"
STATE_THREAD_LOCK = threading.RLock()

app = FastAPI(title="HydroSeismic API", description="Disaster intelligence and emergency-response jury prototype", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["*"])

INITIAL = {
    "mode": "SYNTHETIC_DEMO",
    "zones": [
        {"id":"HZ-01","name":"Riverbank North","lat":13.2185,"lng":79.0972,"risk":"CRITICAL","score":94,"exposure":12800,"population":18300,"hazard":"Flash flood","status":"Alert issued","reason":"Low-lying settlement near river corridor"},
        {"id":"HZ-02","name":"Central Market","lat":13.2048,"lng":79.0941,"risk":"HIGH","score":78,"exposure":7600,"population":22100,"hazard":"Urban flooding","status":"Monitoring","reason":"High population density and drainage constraints"},
        {"id":"HZ-03","name":"Hillview East","lat":13.2308,"lng":79.1194,"risk":"HIGH","score":72,"exposure":4900,"population":9400,"hazard":"Slope instability","status":"Alert issued","reason":"Steep terrain and exposed access road"},
        {"id":"HZ-04","name":"South Industrial Area","lat":13.1846,"lng":79.1077,"risk":"MODERATE","score":54,"exposure":2800,"population":12600,"hazard":"Urban flooding","status":"Monitoring","reason":"Industrial assets and road underpass exposure"},
        {"id":"HZ-05","name":"West Village Cluster","lat":13.2022,"lng":79.0620,"risk":"MODERATE","score":43,"exposure":1900,"population":6800,"hazard":"Flash flood","status":"Preparedness","reason":"Limited road redundancy"},
        {"id":"HZ-06","name":"Lake Road Lowlands","lat":13.2450,"lng":79.0785,"risk":"LOW","score":22,"exposure":500,"population":5100,"hazard":"Waterlogging","status":"Monitoring","reason":"Lower scenario impact in this demo"}
    ],
    "inventory": [
        {"resource":"WATER","quantity":50000,"unit":"litres","icon":"droplet"},
        {"resource":"FOOD","quantity":20000,"unit":"packets","icon":"utensils"},
        {"resource":"MEDICAL_KITS","quantity":3000,"unit":"kits","icon":"briefcase-medical"},
        {"resource":"AMBULANCE","quantity":8,"unit":"vehicles","icon":"ambulance"},
        {"resource":"RESCUE_TEAM","quantity":4,"unit":"teams","icon":"users"}
    ],
    "requests": [
        {"id":"REQ-101","zone_id":"HZ-01","zone":"Riverbank North","resource":"WATER","requested":12000,"recommended":10000,"priority":97,"reason":"Critical flood exposure; prioritize drinking water","status":"PENDING","approval_status":"PENDING","approved":0,"dispatched":0,"delivered":0},
        {"id":"REQ-102","zone_id":"HZ-01","zone":"Riverbank North","resource":"MEDICAL_KITS","requested":420,"recommended":350,"priority":95,"reason":"High exposed population and medical access needs","status":"PENDING","approval_status":"PENDING","approved":0,"dispatched":0,"delivered":0},
        {"id":"REQ-103","zone_id":"HZ-03","zone":"Hillview East","resource":"RESCUE_TEAM","requested":3,"recommended":2,"priority":88,"reason":"Access constraints require staged rescue capacity","status":"PENDING","approval_status":"PENDING","approved":0,"dispatched":0,"delivered":0},
        {"id":"REQ-104","zone_id":"HZ-02","zone":"Central Market","resource":"FOOD","requested":2500,"recommended":2000,"priority":76,"reason":"Dense population; stage food kits near safe distribution point","status":"PENDING","approval_status":"PENDING","approved":0,"dispatched":0,"delivered":0},
        {"id":"REQ-105","zone_id":"HZ-04","zone":"South Industrial Area","resource":"AMBULANCE","requested":2,"recommended":1,"priority":61,"reason":"Maintain one response vehicle on standby","status":"PENDING","approval_status":"PENDING","approved":0,"dispatched":0,"delivered":0}
    ],
    "inventory_movements": [],
    "inventory_reconciliations": [],
    "dispatches": [],
    "deliveries": [],
    "hazard_events": [],
    "events": []
}

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def exclusive_state_access():
    with STATE_THREAD_LOCK:
        with STATE_LOCK_FILE.open("a+b") as lock_file:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"\0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def load_state() -> dict[str, Any]:
    state: dict[str, Any] | None = None
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    if state is None:
        state = json.loads(json.dumps(INITIAL))
        append_event(state, "DEMO_INITIALIZED", "system", "Synthetic demo scenario initialized")

    seeded_ids = {request["id"] for request in INITIAL["requests"]}
    migrated = False
    for request in state.get("requests", []):
        if request.get("id") in seeded_ids and not request.get("requester_id"):
            request["requester_id"] = "system:demo-seed"
            migrated = True
    if "inventory_movements" not in state:
        state["inventory_movements"] = []
        migrated = True
    for collection in ("dispatches", "deliveries", "hazard_events", "inventory_reconciliations"):
        if collection not in state:
            state[collection] = []
            migrated = True
    if migrated or not STATE_FILE.exists():
        save_state(state)
    return state

def save_state(state: dict[str, Any]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=STATE_FILE.parent,
            prefix=f"{STATE_FILE.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(state, temporary_file, indent=2)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, STATE_FILE)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

def append_event(
    state: dict[str, Any],
    event_type: str,
    actor: str,
    message: str,
    request_id: str | None = None,
    *,
    actor_id: str | None = None,
    decision: str | None = None,
    reason: str | None = None,
) -> None:
    prev = state["events"][-1]["hash"] if state["events"] else "GENESIS"
    event = {"event_id": f"AUD-{len(state['events'])+1:04d}", "timestamp": now(), "event_type": event_type, "actor": actor, "message": message, "request_id": request_id, "previous_hash": prev}
    if actor_id is not None:
        event["actor_id"] = actor_id
    if decision is not None:
        event["decision"] = decision
    if reason is not None:
        event["reason"] = reason
    event["hash"] = event_hash(event)
    state["events"].append(event)

def get_state() -> dict[str, Any]:
    with exclusive_state_access():
        return load_state()

class DispatchBody(BaseModel):
    officer_id: str = Field(min_length=3, max_length=80)
    dispatch_qty: int = Field(gt=0)
    vehicle_or_team: str = Field(default="DEMO-UNIT-01", max_length=80)
    source_warehouse: str = Field(default="DEMO-WH-01", min_length=1, max_length=80)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)

class DeliveryBody(BaseModel):
    officer_id: str = Field(min_length=3, max_length=80)
    delivered_qty: int = Field(gt=0)
    note: str = Field(default="Demo delivery confirmation", max_length=500)
    shortage_qty: int = Field(default=0, ge=0)
    shortage_reason: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)

    @model_validator(mode="after")
    def require_shortage_reason(self) -> DeliveryBody:
        if self.shortage_qty and not (self.shortage_reason or "").strip():
            raise ValueError("A reason is required when reporting a delivery shortage")
        if self.shortage_reason is not None:
            self.shortage_reason = self.shortage_reason.strip()
        return self

class DispatchFailureBody(ReasonBody):
    pass

class DispatchTransitionBody(BaseModel):
    status: Literal["IN_TRANSIT"]

class PrepareDispatchBody(BaseModel):
    quantity: int = Field(gt=0)
    source_warehouse: str = Field(default="DEMO-WH-01", min_length=1, max_length=80)
    vehicle_or_team: str = Field(default="DEMO-UNIT-01", max_length=80)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)

class DispatchReconciliationBody(ReasonBody):
    returned_qty: int = Field(gt=0)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)

@app.get("/")
def root(): return {"project":"HydroSeismic","status":"running","mode":"SYNTHETIC_DEMO"}

@app.get("/api/health")
def health(): return {"status":"healthy","service":"HydroSeismic API","timestamp_utc":now()}

@app.get("/api/overview")
def overview():
    return overview_from_state(get_state())

def overview_from_state(s: dict[str, Any]) -> dict[str, Any]:
    requests = s["requests"]
    return {"mode":s["mode"],"active_alerts":sum(z["status"]=="Alert issued" for z in s["zones"]),"zones_under_review":sum(z["risk"] in ("CRITICAL","HIGH") for z in s["zones"]),"pending_approvals":sum(r["approval_status"]=="PENDING" for r in requests),"resources_dispatched":sum(r["dispatched"] for r in requests),"deliveries_confirmed":sum(r["delivered"] for r in requests),"zones_count":len(s["zones"]),"audit_events":len(s["events"]),"message":"Synthetic scenario data for demonstration. Not an operational warning service."}

@app.get("/api/zones")
def zones():
    state = get_state()
    return {"mode":state["mode"],"zones":state["zones"]}

@app.get("/api/inventory")
def inventory():
    return {"inventory":inventory_snapshot(get_state())}

@app.get("/api/inventory/movements")
def inventory_movements(principal: Principal = Depends(require_roles(*AUDIT_ROLES))):
    return {"movements":get_state().get("inventory_movements", [])}

@app.post("/api/inventory/{resource}/adjustments")
def stock_adjustment(
    resource: str,
    body: StockAdjustmentBody,
    principal: Principal = Depends(require_roles(Role.ADMINISTRATOR)),
):
    try:
        with exclusive_state_access():
            state = load_state()
            item = adjust_stock(
                state,
                resource,
                body.delta,
                actor_id=principal.subject,
                reason=body.reason,
            )
            append_event(
                state,
                "INVENTORY_ADJUSTED",
                principal.subject,
                f"Adjusted {resource} stock by {body.delta}. {body.reason}",
                actor_id=principal.subject,
                reason=body.reason,
            )
            save_state(state)
    except InventoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok":True,"inventory":item}

@app.post("/api/inventory/reconcile")
def inventory_reconciliation(
    body: InventoryReconciliationBody,
    principal: Principal = Depends(require_roles(Role.ADMINISTRATOR)),
):
    try:
        with exclusive_state_access():
            state = load_state()
            report = reconcile_inventory(
                state,
                [item.model_dump() for item in body.observations],
                warehouse_id=body.warehouse_id,
            )
            report["report_id"] = f"REC-{len(state.get('inventory_reconciliations', [])) + 1:06d}"
            report["actor_id"] = principal.subject
            state.setdefault("inventory_reconciliations", []).append(report)
            discrepancies = [line for line in report["lines"] if line["discrepancy"]]
            append_event(
                state,
                "INVENTORY_RECONCILIATION_REPORTED",
                principal.subject,
                f"Counted {len(report['lines'])} resources at {body.warehouse_id}; {len(discrepancies)} discrepancies found.",
                actor_id=principal.subject,
                reason="Physical count compared with recorded on-hand stock; report does not adjust inventory.",
            )
            save_state(state)
    except InventoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return report

@app.get("/api/inventory/reconciliations")
def inventory_reconciliation_history(principal: Principal = Depends(require_roles(*AUDIT_ROLES))):
    return {"reports":list(reversed(get_state().get("inventory_reconciliations", [])))}

@app.get("/api/allocations")
def allocations(): return {"requests":get_state()["requests"]}

@app.post("/api/allocations", status_code=201)
def create_allocation(
    body: CreateRequestBody,
    principal: Principal = Depends(require_roles(*REQUESTER_ROLES)),
):
    with exclusive_state_access():
        state=load_state()
        zone=next((item for item in state["zones"] if item["id"]==body.zone_id),None)
        if zone is None: raise HTTPException(404,"Zone not found")
        sequence=len(state["requests"])+1
        request_id=f"REQ-{sequence:06d}"
        existing_ids={item["id"] for item in state["requests"]}
        while request_id in existing_ids:
            sequence+=1
            request_id=f"REQ-{sequence:06d}"
        request={"id":request_id,"zone_id":zone["id"],"zone":zone["name"],"resource":body.resource.value,"requested":body.requested,"recommended":body.requested,"priority":zone["score"],"reason":body.reason,"status":"PENDING","approval_status":"PENDING","approved":0,"dispatched":0,"delivered":0,"shortage":0,"released":0,"requester_id":principal.subject}
        state["requests"].insert(0,request)
        append_event(state,"REQUEST_CREATED",principal.subject,f"Requested {body.requested} {body.resource.value} for {zone['id']}. {body.reason}",request_id,actor_id=principal.subject,reason=body.reason)
        save_state(state)
    return {"ok":True,"request":request}

@app.post("/api/allocations/recommendations", response_model=AllocationSimulation)
def allocation_recommendations(scenario: AllocationScenario):
    return simulate_allocation(scenario)

@app.post("/api/scenarios/simulate", response_model=ScenarioResult)
def simulate_scenario(scenario: ScenarioInput):
    try:
        return simulate_digital_twin(get_state(), scenario)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.post("/api/hazard-events")
def ingest_event(
    body: HazardEventInput,
    principal: Principal = Depends(require_roles(Role.ADMINISTRATOR)),
):
    try:
        with exclusive_state_access():
            state = load_state()
            event = ingest_hazard_event(
                state,
                body.model_dump(mode="json"),
                actor_id=principal.subject,
                known_zone_ids={zone["id"] for zone in state["zones"]},
            )
            save_state(state)
    except AlertError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok":True,"event":event}

@app.get("/api/hazard-events/pending")
def pending_hazard_events(principal: Principal = Depends(require_roles(*REVIEWER_ROLES))):
    events=get_state().get("hazard_events", [])
    return {"events":[event for event in reversed(events) if event["validation_status"]=="PENDING_REVIEW"]}

@app.post("/api/hazard-events/{event_id}/validation")
def review_hazard_event(
    event_id: str,
    body: HazardValidationBody,
    principal: Principal = Depends(require_roles(*REVIEWER_ROLES)),
):
    try:
        with exclusive_state_access():
            state=load_state()
            event=validate_hazard_event(
                state,
                event_id,
                actor_id=principal.subject,
                decision=body.decision,
                reason=body.reason,
            )
            save_state(state)
    except AlertError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok":True,"event":event}

@app.get("/api/alerts")
def alerts(principal: Principal = Depends(require_roles(*(REVIEWER_ROLES + AUDIT_ROLES)))):
    return {
        "alerts":list_active_alerts(get_state()),
        "notification_provider":"NOT_CONFIGURED",
        "note":"Alerts are visible in this dashboard API only; no external warning channel is configured.",
    }

@app.post("/api/alerts/{event_id}/acknowledgements")
def acknowledge_alert_route(
    event_id: str,
    body: AlertAcknowledgementBody,
    principal: Principal = Depends(require_roles(*REVIEWER_ROLES)),
):
    try:
        with exclusive_state_access():
            state=load_state()
            event=acknowledge_alert(
                state,
                event_id,
                actor_id=principal.subject,
                reason=body.reason,
            )
            save_state(state)
    except AlertError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok":True,"event":event}

@app.post("/api/allocations/{request_id}/review")
def review(
    request_id: str,
    body: ApprovalBody,
    principal: Principal = Depends(require_roles(*REVIEWER_ROLES)),
):
    try:
        with exclusive_state_access():
            state = load_state()
            request = review_allocation(
                state,
                request_id,
                principal=principal,
                decision=body.decision,
                reason=body.reason,
                approved_qty=body.approved_qty,
                append_audit=append_event,
            )
            save_state(state)
            response_overview = overview_from_state(state)
    except ApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok":True,"request":request,"overview":response_overview}

@app.post("/api/allocations/{request_id}/dispatch")
def dispatch(
    request_id: str,
    body: DispatchBody,
    principal: Principal = Depends(require_roles(*WAREHOUSE_ROLES)),
):
    with exclusive_state_access():
        s=load_state()
        r=next((x for x in s["requests"] if x["id"]==request_id),None)
        if not r: raise HTTPException(404,"Request not found")
        if r["approval_status"]!="APPROVED": raise HTTPException(409,"Government/demo officer approval is required before dispatch")
        payload={"request_id":request_id,"actor_id":principal.subject,"dispatch_qty":body.dispatch_qty,"source_warehouse":body.source_warehouse,"vehicle_or_team":body.vehicle_or_team}
        key=body.idempotency_key or make_idempotency_key(payload)
        duplicate=next((item for item in s["dispatches"] if item["idempotency_key"]==key),None)
        if duplicate:
            if duplicate["idempotency_payload"]!=payload: raise HTTPException(409,"Idempotency key was already used for a different dispatch")
            return {"ok":True,"request":r,"dispatch":duplicate,"replayed":True}
        prepared=sum(item["quantity"] for item in s["dispatches"] if item["request_id"]==request_id and item["status"]=="PREPARED")
        remaining=r["approved"]-r["dispatched"]-r.get("released", 0)-prepared
        if body.dispatch_qty>remaining: raise HTTPException(400,f"Only {remaining} approved units remain to dispatch")
        r["dispatched"]+=body.dispatch_qty; r["status"]="DISPATCHED" if r["dispatched"]==r["approved"] else "PARTIALLY_DISPATCHED"
        timestamp=now()
        dispatch_record={"dispatch_id":f"DSP-{len(s['dispatches'])+1:06d}","request_id":request_id,"source_warehouse":body.source_warehouse,"destination_zone":r["zone_id"],"resource":r["resource"],"quantity":body.dispatch_qty,"delivered":0,"responsible_actor":principal.subject,"vehicle_or_team":body.vehicle_or_team,"created_at":timestamp,"status":"PREPARED","status_history":[{"status":"PREPARED","timestamp":timestamp,"actor_id":principal.subject,"reason":"Approved request prepared for dispatch"}],"idempotency_key":key,"idempotency_payload":payload}
        dispatch_record["status"]="DISPATCHED"
        dispatch_record["status_history"].append({"status":"DISPATCHED","timestamp":timestamp,"actor_id":principal.subject,"reason":"Shipment dispatched from source warehouse"})
        s["dispatches"].append(dispatch_record)
        append_inventory_movement(s,movement_type="DISPATCHED",actor_id=principal.subject,resource=r["resource"],quantity=body.dispatch_qty,reason=f"Dispatched using {body.vehicle_or_team}",request_id=request_id)
        append_event(s,"RESOURCE_DISPATCHED",principal.subject,f"Dispatched {body.dispatch_qty} using {body.vehicle_or_team}",request_id,actor_id=principal.subject); save_state(s)
    return {"ok":True,"request":r,"dispatch":dispatch_record,"replayed":False}

@app.post("/api/allocations/{request_id}/prepare-dispatch", status_code=201)
def prepare_dispatch(
    request_id: str,
    body: PrepareDispatchBody,
    principal: Principal = Depends(require_roles(*WAREHOUSE_ROLES)),
):
    with exclusive_state_access():
        state=load_state()
        request=next((item for item in state["requests"] if item["id"]==request_id),None)
        if not request: raise HTTPException(404,"Request not found")
        if request["approval_status"]!="APPROVED": raise HTTPException(409,"Only approved requests can be prepared for dispatch")
        payload={"action":"PREPARE","request_id":request_id,"actor_id":principal.subject,"quantity":body.quantity,"source_warehouse":body.source_warehouse,"vehicle_or_team":body.vehicle_or_team}
        key=body.idempotency_key or make_idempotency_key(payload)
        duplicate=next((item for item in state["dispatches"] if item["idempotency_key"]==key),None)
        if duplicate:
            if duplicate["idempotency_payload"]!=payload: raise HTTPException(409,"Idempotency key was already used for a different operation")
            return {"ok":True,"dispatch":duplicate,"replayed":True}
        prepared=sum(item["quantity"] for item in state["dispatches"] if item["request_id"]==request_id and item["status"]=="PREPARED")
        remaining=request["approved"]-request["dispatched"]-request.get("released",0)-prepared
        if body.quantity>remaining: raise HTTPException(400,f"Only {remaining} approved units remain available to prepare")
        timestamp=now()
        record={"dispatch_id":f"DSP-{len(state['dispatches'])+1:06d}","request_id":request_id,"source_warehouse":body.source_warehouse,"destination_zone":request["zone_id"],"resource":request["resource"],"quantity":body.quantity,"delivered":0,"returned":0,"responsible_actor":principal.subject,"vehicle_or_team":body.vehicle_or_team,"created_at":timestamp,"status":"PREPARED","status_history":[{"status":"PREPARED","timestamp":timestamp,"actor_id":principal.subject,"reason":"Approved quantity reserved for shipment preparation"}],"idempotency_key":key,"idempotency_payload":payload}
        state["dispatches"].append(record)
        append_event(state,"DISPATCH_PREPARED",principal.subject,f"Prepared {body.quantity} {request['resource']} units from {body.source_warehouse}.",request_id,actor_id=principal.subject)
        save_state(state)
    return {"ok":True,"dispatch":record,"replayed":False}

@app.post("/api/dispatches/{dispatch_id}/dispatch")
def commit_dispatch(dispatch_id: str, principal: Principal = Depends(require_roles(*WAREHOUSE_ROLES))):
    with exclusive_state_access():
        state=load_state()
        record=next((item for item in state.get("dispatches",[]) if item["dispatch_id"]==dispatch_id),None)
        if not record: raise HTTPException(404,"Dispatch not found")
        if record["status"]!="PREPARED": raise HTTPException(409,"Only prepared shipments can be dispatched")
        request=next((item for item in state["requests"] if item["id"]==record["request_id"]),None)
        if request is None or request["approval_status"]!="APPROVED": raise HTTPException(409,"An active approved request is required")
        remaining=request["approved"]-request["dispatched"]-request.get("released",0)
        if record["quantity"]>remaining: raise HTTPException(409,"Approved quantity changed before dispatch")
        request["dispatched"]+=record["quantity"]
        request["status"]="DISPATCHED" if request["dispatched"]==request["approved"] else "PARTIALLY_DISPATCHED"
        record_dispatch_status(state,record,"DISPATCHED",principal.subject,"Prepared shipment committed to dispatch")
        append_inventory_movement(state,movement_type="DISPATCHED",actor_id=principal.subject,resource=record["resource"],quantity=record["quantity"],reason=f"Dispatched using {record['vehicle_or_team']}",request_id=record["request_id"])
        save_state(state)
    return {"ok":True,"dispatch":record,"request":request}

@app.post("/api/dispatches/{dispatch_id}/cancel")
def cancel_prepared_dispatch(
    dispatch_id: str,
    body: ReasonBody,
    principal: Principal = Depends(require_roles(*WAREHOUSE_ROLES)),
):
    with exclusive_state_access():
        state=load_state()
        record=next((item for item in state.get("dispatches",[]) if item["dispatch_id"]==dispatch_id),None)
        if not record: raise HTTPException(404,"Dispatch not found")
        if record["status"]!="PREPARED": raise HTTPException(409,"Only prepared shipments can be canceled")
        record_dispatch_status(state,record,"CANCELED",principal.subject,body.reason)
        save_state(state)
    return {"ok":True,"dispatch":record}

@app.post("/api/allocations/{request_id}/delivery")
def delivery(
    request_id: str,
    body: DeliveryBody,
    principal: Principal = Depends(require_roles(*WAREHOUSE_ROLES)),
):
    with exclusive_state_access():
        s=load_state()
        r=next((x for x in s["requests"] if x["id"]==request_id),None)
        if not r: raise HTTPException(404,"Request not found")
        payload={"request_id":request_id,"actor_id":principal.subject,"delivered_qty":body.delivered_qty,"shortage_qty":body.shortage_qty,"shortage_reason":body.shortage_reason,"note":body.note}
        key=body.idempotency_key or make_idempotency_key(payload)
        duplicate=next((item for item in s["deliveries"] if item["idempotency_key"]==key),None)
        if duplicate:
            if duplicate["idempotency_payload"]!=payload: raise HTTPException(409,"Idempotency key was already used for a different delivery")
            return {"ok":True,"request":r,"delivery":duplicate,"replayed":True}
        remaining=r["dispatched"]-r["delivered"]-r.get("shortage", 0)
        accounted_qty=body.delivered_qty+body.shortage_qty
        if accounted_qty>remaining: raise HTTPException(400,f"Only {remaining} dispatched units can be accounted for")
        if body.delivered_qty<1: raise HTTPException(400,"Delivery quantity must be greater than zero")
        eligible_dispatches=[item for item in s["dispatches"] if item["request_id"]==request_id and item["status"] in {"DISPATCHED","IN_TRANSIT","PARTIALLY_DELIVERED"} and item["delivered"]+item.get("shortage", 0)<item["quantity"]]
        legacy_available=max(0,r["dispatched"]-sum(item["quantity"] for item in s["dispatches"] if item["request_id"]==request_id))
        deliverable=sum(item["quantity"]-item["delivered"]-item.get("shortage", 0) for item in eligible_dispatches)+legacy_available
        if accounted_qty>deliverable: raise HTTPException(409,"Delivery quantities exceed active shipment quantities")
        delivery_left=body.delivered_qty
        shortage_left=body.shortage_qty
        timestamp=now()
        for shipment in eligible_dispatches:
            capacity=shipment["quantity"]-shipment["delivered"]-shipment.get("shortage", 0)
            actual_delivery=min(capacity,delivery_left)
            reported_shortage=min(capacity-actual_delivery,shortage_left)
            if actual_delivery or reported_shortage:
                if actual_delivery:
                    shipment["delivered"]+=actual_delivery
                if reported_shortage:
                    shipment["shortage"]=shipment.get("shortage", 0)+reported_shortage
                delivery_left-=actual_delivery
                shortage_left-=reported_shortage
                accounted=shipment["delivered"]+shipment.get("shortage", 0)
                shipment["status"]="DELIVERED" if accounted==shipment["quantity"] and shipment.get("shortage", 0)==0 else "DELIVERY_FAILED" if accounted==shipment["quantity"] and shipment["delivered"]==0 else "PARTIALLY_DELIVERED"
                shipment["status_history"].append({"status":shipment["status"],"timestamp":timestamp,"actor_id":principal.subject,"reason":body.note,"delivered_quantity":actual_delivery,"shortage_quantity":reported_shortage,"shortage_reason":body.shortage_reason})
            if delivery_left + shortage_left == 0: break
        delivered_qty=payload["delivered_qty"]
        shortage_qty=payload["shortage_qty"]
        r["delivered"]+=delivered_qty
        r["shortage"]=r.get("shortage", 0)+shortage_qty
        r["status"]="DELIVERED" if r["delivered"]==r["approved"] else "PARTIALLY_DELIVERED"
        receipt={"delivery_id":f"DLV-{len(s['deliveries'])+1:06d}","request_id":request_id,"quantity":delivered_qty,"shortage":shortage_qty,"shortage_reason":body.shortage_reason,"actor_id":principal.subject,"timestamp":timestamp,"note":body.note,"idempotency_key":key,"idempotency_payload":payload}
        s["deliveries"].append(receipt)
        append_inventory_movement(s,movement_type="DELIVERED",actor_id=principal.subject,resource=r["resource"],quantity=delivered_qty,reason=body.note,request_id=request_id)
        if shortage_qty:
            append_inventory_movement(s,movement_type="SHORTAGE_REPORTED",actor_id=principal.subject,resource=r["resource"],quantity=shortage_qty,reason=body.shortage_reason or "",request_id=request_id)
        event_type="DELIVERY_SHORTAGE_REPORTED" if shortage_qty else "DELIVERY_CONFIRMED"
        append_event(s,event_type,principal.subject,f"Confirmed {delivered_qty} delivered and reported {shortage_qty} short. {body.note}",request_id,actor_id=principal.subject,reason=body.shortage_reason); save_state(s)
    return {"ok":True,"request":r,"delivery":receipt,"replayed":False}

def make_idempotency_key(payload: dict[str, Any]) -> str:
    serialized=json.dumps(payload,sort_keys=True,separators=(",", ":")).encode()
    return sha256(serialized).hexdigest()

def record_dispatch_status(state: dict[str, Any], dispatch_record: dict[str, Any], status: str, actor_id: str, reason: str) -> None:
    timestamp=now()
    dispatch_record["status"]=status
    dispatch_record["status_history"].append({"status":status,"timestamp":timestamp,"actor_id":actor_id,"reason":reason})
    append_event(state,f"DISPATCH_{status}",actor_id,f"Dispatch {dispatch_record['dispatch_id']} status changed to {status}. {reason}",dispatch_record["request_id"],actor_id=actor_id,reason=reason)

@app.get("/api/dispatches")
def dispatches(principal: Principal = Depends(require_roles(*(WAREHOUSE_ROLES + AUDIT_ROLES)))):
    return {"dispatches":list(reversed(get_state().get("dispatches", [])))}

@app.get("/api/dispatches/{dispatch_id}")
def get_dispatch(dispatch_id: str, principal: Principal = Depends(require_roles(*(WAREHOUSE_ROLES + AUDIT_ROLES)))):
    record=next((item for item in get_state().get("dispatches", []) if item["dispatch_id"]==dispatch_id),None)
    if not record: raise HTTPException(404,"Dispatch not found")
    return {"dispatch":record,"timeline":record["status_history"]}

@app.post("/api/dispatches/{dispatch_id}/transit")
def mark_in_transit(dispatch_id: str, body: DispatchTransitionBody, principal: Principal = Depends(require_roles(*WAREHOUSE_ROLES))):
    with exclusive_state_access():
        state=load_state()
        record=next((item for item in state.get("dispatches", []) if item["dispatch_id"]==dispatch_id),None)
        if not record: raise HTTPException(404,"Dispatch not found")
        if record["status"]!="DISPATCHED": raise HTTPException(409,"Only dispatched shipments can enter transit")
        record_dispatch_status(state,record,body.status,principal.subject,"Shipment accepted for transit")
        save_state(state)
    return {"ok":True,"dispatch":record}

@app.post("/api/dispatches/{dispatch_id}/failure")
def fail_dispatch(dispatch_id: str, body: DispatchFailureBody, principal: Principal = Depends(require_roles(*WAREHOUSE_ROLES))):
    with exclusive_state_access():
        state=load_state()
        record=next((item for item in state.get("dispatches", []) if item["dispatch_id"]==dispatch_id),None)
        if not record: raise HTTPException(404,"Dispatch not found")
        if record["status"] not in {"DISPATCHED","IN_TRANSIT","PARTIALLY_DELIVERED"}: raise HTTPException(409,"Shipment cannot be marked failed from its current state")
        record_dispatch_status(state,record,"DELIVERY_FAILED",principal.subject,body.reason)
        save_state(state)
    return {"ok":True,"dispatch":record}

@app.post("/api/dispatches/{dispatch_id}/reconcile")
def reconcile_dispatch(
    dispatch_id: str,
    body: DispatchReconciliationBody,
    principal: Principal = Depends(require_roles(Role.ADMINISTRATOR)),
):
    with exclusive_state_access():
        state=load_state()
        record=next((item for item in state.get("dispatches", []) if item["dispatch_id"]==dispatch_id),None)
        if not record: raise HTTPException(404,"Dispatch not found")
        payload={"dispatch_id":dispatch_id,"actor_id":principal.subject,"returned_qty":body.returned_qty,"reason":body.reason}
        key=body.idempotency_key or make_idempotency_key(payload)
        reconciliation_records=record.setdefault("reconciliations",[])
        duplicate=next((item for item in reconciliation_records if item["idempotency_key"]==key),None)
        if duplicate:
            if duplicate["idempotency_payload"]!=payload: raise HTTPException(409,"Idempotency key was already used for a different reconciliation")
            return {"ok":True,"dispatch":record,"reconciliation":duplicate,"replayed":True}
        if record["status"]!="DELIVERY_FAILED": raise HTTPException(409,"Only failed shipments can be reconciled")
        request=next((item for item in state["requests"] if item["id"]==record["request_id"]),None)
        if request is None: raise HTTPException(409,"Shipment request is missing")
        returnable=record["quantity"]-record["delivered"]-record.get("shortage",0)-record.get("returned",0)
        if body.returned_qty>returnable: raise HTTPException(400,f"Only {returnable} undistributed units can be returned")
        if body.returned_qty>request["dispatched"]-request["delivered"]-request.get("shortage",0):
            raise HTTPException(409,"Return quantity exceeds the request's outstanding dispatched amount")
        record["returned"]=record.get("returned",0)+body.returned_qty
        reconciliation={"reconciliation_id":f"RCL-{len(reconciliation_records)+1:06d}","actor_id":principal.subject,"timestamp":now(),"returned_quantity":body.returned_qty,"reason":body.reason,"idempotency_key":key,"idempotency_payload":payload}
        reconciliation_records.append(reconciliation)
        request["dispatched"]-=body.returned_qty
        request["status"]="APPROVED" if request["dispatched"]==0 else "PARTIALLY_DISPATCHED"
        remaining=record["quantity"]-record["delivered"]-record.get("shortage",0)-record["returned"]
        if remaining==0:
            record["status"]="RECONCILED"
            record["status_history"].append({"status":"RECONCILED","timestamp":reconciliation["timestamp"],"actor_id":principal.subject,"reason":body.reason,"returned_quantity":body.returned_qty})
        else:
            record["status_history"].append({"status":"RETURN_RECONCILED","timestamp":reconciliation["timestamp"],"actor_id":principal.subject,"reason":body.reason,"returned_quantity":body.returned_qty})
        append_inventory_movement(state,movement_type="RETURNED_TO_INVENTORY",actor_id=principal.subject,resource=record["resource"],quantity=body.returned_qty,reason=body.reason,request_id=record["request_id"])
        append_event(state,"FAILED_DISPATCH_RECONCILED",principal.subject,f"Returned {body.returned_qty} {record['resource']} units from failed dispatch {dispatch_id} to inventory.",record["request_id"],actor_id=principal.subject,decision="RETURN_TO_STOCK",reason=body.reason)
        save_state(state)
    return {"ok":True,"dispatch":record,"reconciliation":reconciliation,"replayed":False}

@app.post("/api/allocations/{request_id}/cancel")
def cancel_allocation(
    request_id: str,
    body: ReasonBody,
    principal: Principal = Depends(require_roles(*REVIEWER_ROLES)),
):
    try:
        with exclusive_state_access():
            state = load_state()
            request, released = release_unused_reservation(
                state,
                request_id,
                actor_id=principal.subject,
                reason=body.reason,
            )
            append_event(
                state,
                "ALLOCATION_CANCELED",
                principal.subject,
                f"Released {released} reserved {request['resource']} units. {body.reason}",
                request_id,
                actor_id=principal.subject,
                decision="CANCEL",
                reason=body.reason,
            )
            save_state(state)
    except InventoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok":True,"request":request,"released":released}

@app.get("/api/audit")
def audit(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    event_type: str | None = Query(default=None, max_length=80),
    request_id: str | None = Query(default=None, max_length=80),
    principal: Principal = Depends(require_roles(*AUDIT_ROLES)),
):
    events=get_state()["events"]
    integrity = verify_chain(events)
    filtered = [
        event
        for event in reversed(events)
        if (event_type is None or event["event_type"] == event_type)
        and (request_id is None or event.get("request_id") == request_id)
    ]
    start = (page - 1) * page_size
    return {
        **integrity,
        "ledger_type":"LOCAL_DEMO_HASH_CHAIN",
        "note":"A local hash-chain demonstration, not a deployed blockchain or legal government approval system.",
        "page":page,
        "page_size":page_size,
        "total":len(filtered),
        "events":filtered[start:start + page_size],
    }

@app.post("/api/reset-demo")
def reset_demo(principal: Principal = Depends(require_roles(Role.ADMINISTRATOR))):
    if os.getenv("HYDROSEISMIC_ALLOW_RESET","true").lower()!="true": raise HTTPException(403,"Demo reset is disabled")
    with exclusive_state_access():
        if STATE_FILE.exists(): STATE_FILE.unlink()
    return {"ok":True,"message":"Demo state reset. Reload the dashboard."}
