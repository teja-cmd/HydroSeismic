"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ClipboardCheck } from "lucide-react";

type InventoryItem = { resource: string; on_hand: number; unit: string };
type Reconciliation = { report_id: string; actor_id: string; warehouse_id: string; generated_at: string; mutated_inventory: boolean; lines: Array<{ resource: string; expected_on_hand: number; observed_quantity: number; discrepancy: number; status: string }> };
type InventoryMovement = { movement_id: string; timestamp: string; movement_type: string; actor_id: string; resource: string; quantity: number; reason: string; request_id: string | null };
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function InventoryReconciliation({ inventory, token, onComplete }: { inventory: InventoryItem[]; token: string; onComplete: () => Promise<void> }) {
  const [observed, setObserved] = useState<Record<string, string>>({});
  const [report, setReport] = useState<Reconciliation | null>(null);
  const [reports, setReports] = useState<Reconciliation[]>([]);
  const [movements, setMovements] = useState<InventoryMovement[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [resource, setResource] = useState(inventory[0]?.resource ?? "");
  const [delta, setDelta] = useState("");
  const [adjustmentReason, setAdjustmentReason] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setObserved(current => Object.fromEntries(inventory.map(item => [item.resource, current[item.resource] ?? String(item.on_hand)])));
    if (!resource && inventory.length) setResource(inventory[0].resource);
  }, [inventory, resource]);
  useEffect(() => {
    let cancelled = false;
    async function loadHistory() {
      if (!token) { setReports([]); setMovements([]); setHistoryError("Administrator or auditor token required to view inventory history."); return; }
      try {
        const headers = { Authorization: `Bearer ${token}` };
        const [movementResponse, reportResponse] = await Promise.all([
          fetch(`${API}/api/inventory/movements`, { cache: "no-store", headers }),
          fetch(`${API}/api/inventory/reconciliations`, { cache: "no-store", headers }),
        ]);
        const [movementData, reportData] = await Promise.all([movementResponse.json(), reportResponse.json()]);
        if (!movementResponse.ok) throw new Error(movementData.detail || "Inventory movement history unavailable");
        if (!reportResponse.ok) throw new Error(reportData.detail || "Reconciliation history unavailable");
        if (!cancelled) { setMovements(movementData.movements); setReports(reportData.reports); setHistoryError(""); }
      } catch (cause) {
        if (!cancelled) setHistoryError(cause instanceof Error ? cause.message : "Inventory history unavailable");
      }
    }
    void loadHistory();
    return () => { cancelled = true; };
  }, [token]);

  async function reconcile() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/inventory/reconcile`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ warehouse_id: "DEMO-WH-01", observations: inventory.map(item => ({ resource: item.resource, observed_quantity: Number(observed[item.resource]) })) }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Inventory reconciliation failed");
      setReport(data);
      await onComplete();
      const historyResponse = await fetch(`${API}/api/inventory/reconciliations`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      if (historyResponse.ok) setReports((await historyResponse.json()).reports);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Inventory reconciliation failed");
    } finally {
      setLoading(false);
    }
  }

  async function adjustStock() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/inventory/${encodeURIComponent(resource)}/adjustments`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ delta: Number(delta), reason: adjustmentReason }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Stock adjustment failed");
      setDelta("");
      setAdjustmentReason("");
      await onComplete();
      const historyResponse = await fetch(`${API}/api/inventory/movements`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      if (historyResponse.ok) setMovements((await historyResponse.json()).movements);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Stock adjustment failed");
    } finally {
      setLoading(false);
    }
  }

  return <>
    <section className="panel"><div className="panel-head"><div><h2>Physical count reconciliation</h2><p>Compares observed stock with ledger-derived on-hand; does not adjust inventory.</p></div><ClipboardCheck size={18}/></div>{!token && <div className="api-access-notice"><AlertTriangle size={16}/><span>Administrator OIDC token required.</span></div>}<div className="table-scroll"><table><thead><tr><th>Resource</th><th>Expected on-hand</th><th>Observed count</th></tr></thead><tbody>{inventory.map(item => <tr key={item.resource}><td>{item.resource.replaceAll("_", " ")} ({item.unit})</td><td>{item.on_hand}</td><td><input aria-label={`Observed ${item.resource}`} type="number" min="0" value={observed[item.resource] ?? ""} onChange={event => setObserved(current => ({ ...current, [item.resource]: event.target.value }))}/></td></tr>)}</tbody></table></div><div className="request-actions"><button className="btn btn-primary" onClick={() => void reconcile()} disabled={!token || loading || !inventory.length}><ClipboardCheck size={14}/>{loading ? "Checking…" : "Compare counts"}</button></div>{error && <div className="api-access-notice"><AlertTriangle size={16}/><span>{error}</span></div>}{report && <div className="table-scroll reconciliation-results"><table><thead><tr><th>Resource</th><th>Expected</th><th>Observed</th><th>Difference</th><th>Result</th></tr></thead><tbody>{report.lines.map(line => <tr key={line.resource}><td>{line.resource}</td><td>{line.expected_on_hand}</td><td>{line.observed_quantity}</td><td>{line.discrepancy}</td><td>{line.status}</td></tr>)}</tbody></table><p>Report {report.report_id} · {report.warehouse_id} · Inventory changed: {String(report.mutated_inventory)}</p></div>}</section>
    <section className="panel"><div className="panel-head"><div><h2>Verified stock adjustment</h2><p>Administrator action with a required reason; reserved stock cannot be removed.</p></div></div><div className="form-grid scenario-inputs"><div className="field"><label htmlFor="adjustResource">Resource</label><select id="adjustResource" value={resource} onChange={event => setResource(event.target.value)}>{inventory.map(item => <option key={item.resource} value={item.resource}>{item.resource.replaceAll("_", " ")}</option>)}</select></div><div className="field"><label htmlFor="adjustDelta">Stock change</label><input id="adjustDelta" type="number" value={delta} onChange={event => setDelta(event.target.value)} placeholder="Positive or negative units"/></div><div className="field full"><label htmlFor="adjustReason">Reason</label><input id="adjustReason" value={adjustmentReason} onChange={event => setAdjustmentReason(event.target.value)} maxLength={500}/></div></div><div className="request-actions"><button className="btn btn-secondary" onClick={() => void adjustStock()} disabled={!token || loading || !resource || !delta || !adjustmentReason.trim()}>Apply adjustment</button></div></section>
    <section className="panel"><div className="panel-head"><div><h2>Inventory movement history</h2><p>Reservations, dispatches, receipts, returns, and adjustments.</p></div><span className="pending-badge">{movements.length} records</span></div>{historyError && <div className="api-access-notice"><AlertTriangle size={16}/><span>{historyError}</span></div>}{!historyError && !movements.length && <div className="empty-state">No stock movements yet.</div>}{movements.length > 0 && <div className="table-scroll"><table><thead><tr><th>Time</th><th>Type</th><th>Resource</th><th>Quantity</th><th>Actor</th><th>Request</th><th>Reason</th></tr></thead><tbody>{movements.map(item => <tr key={item.movement_id}><td>{new Date(item.timestamp).toLocaleString()}</td><td>{item.movement_type.replaceAll("_", " ")}</td><td>{item.resource}</td><td>{item.quantity}</td><td>{item.actor_id}</td><td>{item.request_id ?? "—"}</td><td>{item.reason}</td></tr>)}</tbody></table></div>}</section>
    <section className="panel"><div className="panel-head"><div><h2>Count reconciliation history</h2><p>Physical count reports preserve differences without changing stock.</p></div><span className="pending-badge">{reports.length} reports</span></div>{!historyError && !reports.length && <div className="empty-state">No count reports recorded.</div>}{reports.map(item => <div className="reconciliation-results" key={item.report_id}><b>{item.report_id} · {item.warehouse_id}</b><span> · {new Date(item.generated_at).toLocaleString()} · {item.actor_id}</span><div className="table-scroll"><table><thead><tr><th>Resource</th><th>Expected</th><th>Observed</th><th>Difference</th><th>Result</th></tr></thead><tbody>{item.lines.map(line => <tr key={line.resource}><td>{line.resource}</td><td>{line.expected_on_hand}</td><td>{line.observed_quantity}</td><td>{line.discrepancy}</td><td>{line.status}</td></tr>)}</tbody></table></div></div>)}</section>
  </>;
}