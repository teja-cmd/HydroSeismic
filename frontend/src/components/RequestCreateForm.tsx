"use client";

import { useState } from "react";
import { AlertTriangle, Send } from "lucide-react";

type Zone = { id: string; name: string };
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const resources = ["WATER", "FOOD", "MEDICAL_KITS", "AMBULANCE", "RESCUE_TEAM"];

export default function RequestCreateForm({ zones, token, onComplete }: { zones: Zone[]; token: string; onComplete: () => Promise<void> }) {
  const [zoneId, setZoneId] = useState(zones[0]?.id ?? "");
  const [resource, setResource] = useState("WATER");
  const [quantity, setQuantity] = useState("100");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit() {
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      const response = await fetch(`${API}/api/allocations`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ zone_id: zoneId, resource, requested: Number(quantity), reason }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Request creation failed");
      setSuccess(`${data.request.id} submitted for independent approval.`);
      setQuantity("100");
      setReason("");
      await onComplete();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Request creation failed");
    } finally {
      setLoading(false);
    }
  }

  return <section className="panel"><div className="panel-head"><div><h2>New relief request</h2><p>Requester identity is taken from the verified OIDC subject. Self-approval is blocked by the API.</p></div></div>{!token && <div className="api-access-notice"><AlertTriangle size={16}/><span>Use a requester, government-officer, or administrator token to submit.</span></div>}<div className="form-grid scenario-inputs"><div className="field"><label htmlFor="newRequestZone">Target zone</label><select id="newRequestZone" value={zoneId} onChange={event => setZoneId(event.target.value)}>{zones.map(zone => <option key={zone.id} value={zone.id}>{zone.id} · {zone.name}</option>)}</select></div><div className="field"><label htmlFor="newRequestResource">Resource</label><select id="newRequestResource" value={resource} onChange={event => setResource(event.target.value)}>{resources.map(value => <option key={value}>{value}</option>)}</select></div><div className="field"><label htmlFor="newRequestQuantity">Requested quantity</label><input id="newRequestQuantity" type="number" min="1" max="1000000" value={quantity} onChange={event => setQuantity(event.target.value)}/></div><div className="field full"><label htmlFor="newRequestReason">Justification</label><input id="newRequestReason" value={reason} onChange={event => setReason(event.target.value)} maxLength={500}/></div></div><div className="request-actions"><button className="btn btn-primary" onClick={() => void submit()} disabled={!token || loading || !zoneId || Number(quantity) < 1 || !reason.trim()}><Send size={14}/>{loading ? "Submitting…" : "Submit for approval"}</button></div>{error && <div className="api-access-notice"><AlertTriangle size={16}/><span>{error}</span></div>}{success && <div className="success-notice">{success}</div>}</section>;
}