"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, RefreshCw, Send } from "lucide-react";

type DispatchRecord = { dispatch_id: string; request_id: string; source_warehouse: string; destination_zone: string; resource: string; quantity: number; delivered: number; returned?: number; status: string; status_history: Array<{ status: string; timestamp: string; actor_id: string; reason: string }> };
type RequestItem = { id: string; zone: string; resource: string; approved: number; dispatched: number; released?: number; approval_status: string };
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function DispatchWorkspace({ token, requests, onComplete }: { token: string; requests: RequestItem[]; onComplete: () => Promise<void> }) {
  const [dispatches, setDispatches] = useState<DispatchRecord[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [reason, setReason] = useState("Route access failure");
  const [returned, setReturned] = useState<Record<string, string>>({});
  const [requestId, setRequestId] = useState("");
  const [prepareQuantity, setPrepareQuantity] = useState("");
  const [warehouse, setWarehouse] = useState("DEMO-WH-01");
  const approvedRequests = requests.filter(item => item.approval_status === "APPROVED" && item.approved - item.dispatched - (item.released ?? 0) > 0);

  async function refresh() {
    if (!token) { setDispatches([]); setError("Apply an OIDC token with warehouse or audit access to view shipments."); return; }
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/dispatches`, { cache: "no-store", headers: { Authorization: `Bearer ${token}` } });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to load shipment records");
      setDispatches(data.dispatches);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load shipment records");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, [token]);
  useEffect(() => {
    if (!requestId && approvedRequests.length) {
      setRequestId(approvedRequests[0].id);
      setPrepareQuantity(String(approvedRequests[0].approved - approvedRequests[0].dispatched - (approvedRequests[0].released ?? 0)));
    }
  }, [requestId, approvedRequests]);

  function selectRequest(id: string) {
    setRequestId(id);
    const selected = approvedRequests.find(item => item.id === id);
    setPrepareQuantity(selected ? String(selected.approved - selected.dispatched - (selected.released ?? 0)) : "");
  }

  async function prepare() {
    const selected = approvedRequests.find(item => item.id === requestId);
    if (!selected) return;
    await transition(`/api/allocations/${requestId}/prepare-dispatch`, {
      quantity: Number(prepareQuantity),
      source_warehouse: warehouse,
      idempotency_key: `prepare-${crypto.randomUUID()}`,
    }, "Shipment prepared");
  }

  async function transition(path: string, body: unknown, success: string) {
    try {
      const response = await fetch(`${API}${path}`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Shipment update failed");
      setError("");
      setNotice(success);
      await refresh();
      await onComplete();
    } catch (cause) {
      setNotice("");
      setError(cause instanceof Error ? cause.message : "Shipment update failed");
    }
  }

  return <section className="panel">
    <div className="panel-head"><div><h2>Shipment tracking</h2><p>API-backed records; no GPS source is connected.</p></div><button className="btn btn-secondary" onClick={() => void refresh()} disabled={loading}><RefreshCw size={14}/>Refresh</button></div>
    {error && <div className="api-access-notice"><AlertTriangle size={16}/><span>{error}</span></div>}
    {notice && <div className="success-notice"><CheckCircle2 size={15}/>{notice}</div>}
    <div className="dispatch-prepare"><div className="panel-head"><div><h2>Prepare approved allocation</h2><p>Preparation holds approved capacity; stock is consumed only when dispatch is committed.</p></div></div><div className="form-grid scenario-inputs"><div className="field"><label htmlFor="prepareRequest">Approved request</label><select id="prepareRequest" value={requestId} onChange={event => selectRequest(event.target.value)}><option value="">Select request</option>{approvedRequests.map(item => <option key={item.id} value={item.id}>{item.id} · {item.zone} · {item.resource}</option>)}</select></div><div className="field"><label htmlFor="prepareQuantity">Quantity</label><input id="prepareQuantity" type="number" min="1" value={prepareQuantity} onChange={event => setPrepareQuantity(event.target.value)}/></div><div className="field"><label htmlFor="prepareWarehouse">Source warehouse</label><input id="prepareWarehouse" value={warehouse} onChange={event => setWarehouse(event.target.value)} maxLength={80}/></div></div><div className="request-actions"><button className="btn btn-primary" onClick={() => void prepare()} disabled={!token || !requestId || Number(prepareQuantity) < 1 || !warehouse.trim()}>Prepare shipment</button></div></div>
    {!error && !dispatches.length && <div className="empty-state">No shipment records yet.</div>}
    <div className="dispatch-list">{dispatches.map(item => <article className="request-card" key={item.dispatch_id}>
      <div className="request-card-top"><div><b>{item.dispatch_id} · {item.resource.replaceAll("_", " ")}</b><p>{item.request_id} · {item.destination_zone} · {item.quantity} units</p></div><span className="state-badge pending">{item.status.replaceAll("_", " ")}</span></div>
      <p>Source: {item.source_warehouse} · Delivered: {item.delivered} · Returned: {item.returned ?? 0}</p>
      <div className="dispatch-timeline">{item.status_history.map((entry, index) => <div className="timeline-event" key={`${entry.timestamp}-${index}`}><CheckCircle2 size={14}/><div><b>{entry.status.replaceAll("_", " ")}</b><span>{new Date(entry.timestamp).toLocaleString()} · {entry.actor_id}</span><small>{entry.reason}</small></div></div>)}</div>
      <div className="request-actions">{item.status === "PREPARED" && <><button className="btn btn-primary" onClick={() => void transition(`/api/dispatches/${item.dispatch_id}/dispatch`, {}, "Shipment dispatched")}><Send size={14}/>Commit dispatch</button><button className="btn btn-danger-outline" onClick={() => void transition(`/api/dispatches/${item.dispatch_id}/cancel`, { reason }, "Prepared shipment canceled")} disabled={!reason.trim()}>Cancel preparation</button></>}{item.status === "DISPATCHED" && <button className="btn btn-primary" onClick={() => void transition(`/api/dispatches/${item.dispatch_id}/transit`, { status: "IN_TRANSIT" }, "Marked in transit")}><Send size={14}/>Mark in transit</button>}{["DISPATCHED", "IN_TRANSIT", "PARTIALLY_DELIVERED"].includes(item.status) && <button className="btn btn-danger-outline" onClick={() => void transition(`/api/dispatches/${item.dispatch_id}/failure`, { reason }, "Delivery failure recorded")} disabled={!reason.trim()}>Report failure</button>}{item.status === "DELIVERY_FAILED" && <><input aria-label={`Returned quantity for ${item.dispatch_id}`} type="number" min="1" max={item.quantity - item.delivered} value={returned[item.dispatch_id] ?? ""} onChange={event => setReturned(current => ({ ...current, [item.dispatch_id]: event.target.value }))} placeholder="Returned units"/><button className="btn btn-secondary" onClick={() => void transition(`/api/dispatches/${item.dispatch_id}/reconcile`, { returned_qty: Number(returned[item.dispatch_id]), reason }, "Return reconciled")} disabled={!returned[item.dispatch_id] || !reason.trim()}>Reconcile return</button></>}</div>
    </article>)}</div>
    {dispatches.length > 0 && <div className="field dispatch-reason"><label htmlFor="dispatchReason">Failure or return reason</label><input id="dispatchReason" value={reason} onChange={event => setReason(event.target.value)} maxLength={500}/></div>}
  </section>;
}