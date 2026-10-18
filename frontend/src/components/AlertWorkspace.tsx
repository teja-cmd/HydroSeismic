"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Check, RefreshCw } from "lucide-react";

type HazardEvent = { event_id: string; source: string; source_event_id: string; event_type: string; severity: string; event_time: string; observed_at: string; expires_at: string; target_zone_ids: string[]; validation_status: string; validation: { actor_id: string; reason: string } | null; acknowledgements: Array<{ actor_id: string; timestamp: string; reason: string }>; notification_status: string };
type Zone = { id: string; name: string };
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

function localDateTime(offsetMs: number) {
  const date = new Date(Date.now() + offsetMs);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

export default function AlertWorkspace({ token, zones }: { token: string; zones: Zone[] }) {
  const [pending, setPending] = useState<HazardEvent[]>([]);
  const [active, setActive] = useState<HazardEvent[]>([]);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("Checked against source information");
  const [loading, setLoading] = useState(false);
  const [source, setSource] = useState("");
  const [sourceEventId, setSourceEventId] = useState("");
  const [eventType, setEventType] = useState("FLOOD_OBSERVED");
  const [severity, setSeverity] = useState("HIGH");
  const [targetZoneIds, setTargetZoneIds] = useState<string[]>([]);
  const [eventTime, setEventTime] = useState(localDateTime(-5 * 60 * 1000));
  const [observedAt, setObservedAt] = useState(localDateTime(0));
  const [expiresAt, setExpiresAt] = useState(localDateTime(60 * 60 * 1000));
  const [confidence, setConfidence] = useState("0.8");

  useEffect(() => {
    if (!targetZoneIds.length && zones.length) setTargetZoneIds([zones[0].id]);
  }, [targetZoneIds, zones]);

  async function refresh() {
    if (!token) { setPending([]); setActive([]); setError("Apply an OIDC token with government-officer or auditor access to view alerts."); return; }
    setLoading(true);
    setError("");
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const [pendingResponse, activeResponse] = await Promise.all([
        fetch(`${API}/api/hazard-events/pending`, { cache: "no-store", headers }),
        fetch(`${API}/api/alerts`, { cache: "no-store", headers }),
      ]);
      const [pendingData, activeData] = await Promise.all([pendingResponse.json(), activeResponse.json()]);
      if (!activeResponse.ok) throw new Error(activeData.detail || "Unable to load active alerts");
      if (!pendingResponse.ok && pendingResponse.status !== 403) throw new Error(pendingData.detail || "Unable to load hazard review queue");
      setPending(pendingResponse.ok ? pendingData.events : []);
      setActive(activeData.alerts);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load alerts");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, [token]);

  async function mutate(path: string, body: unknown) {
    try {
      const response = await fetch(`${API}${path}`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Alert update failed");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Alert update failed");
    }
  }

  async function submitSourceEvent() {
    try {
      const response = await fetch(`${API}/api/hazard-events`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          source,
          source_event_id: sourceEventId,
          event_type: eventType,
          event_time: new Date(eventTime).toISOString(),
          observed_at: new Date(observedAt).toISOString(),
          expires_at: new Date(expiresAt).toISOString(),
          confidence: confidence === "" ? null : Number(confidence),
          severity,
          target_zone_ids: targetZoneIds,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Hazard event intake failed");
      setError("");
      setSourceEventId("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Hazard event intake failed");
    }
  }

  function eventCard(event: HazardEvent, review = false) {
    return <article className="request-card" key={event.event_id}><div className="request-card-top"><div><b>{event.event_type.replaceAll("_", " ")} · {event.severity}</b><p>{event.source} / {event.source_event_id}</p></div><span className="state-badge pending">{event.validation_status.replaceAll("_", " ")}</span></div><p>Zones: {event.target_zone_ids.join(", ")} · Observed {new Date(event.observed_at).toLocaleString()}</p><p>Expires {new Date(event.expires_at).toLocaleString()} · Notification: {event.notification_status.replaceAll("_", " ")}</p>{event.validation && <p>Reviewed by {event.validation.actor_id}: {event.validation.reason}</p>}<div className="request-actions">{review && <><button className="btn btn-primary" onClick={() => void mutate(`/api/hazard-events/${event.event_id}/validation`, { decision: "VALIDATE", reason })}><Check size={14}/>Validate</button><button className="btn btn-danger-outline" onClick={() => void mutate(`/api/hazard-events/${event.event_id}/validation`, { decision: "REJECT", reason })}>Reject</button></>}{!review && !event.acknowledgements.length && <button className="btn btn-secondary" onClick={() => void mutate(`/api/alerts/${event.event_id}/acknowledgements`, { reason })}>Acknowledge</button>}</div>{event.acknowledgements.map(ack => <p key={`${ack.actor_id}-${ack.timestamp}`}>Acknowledged by {ack.actor_id} · {ack.reason}</p>)}</article>;
  }

  return <>
    <section className="panel"><div className="panel-head"><div><h2>Ingest sourced event</h2><p>Admin-submitted source metadata; this does not verify an external provider.</p></div><span className="pill-demo">PENDING REVIEW</span></div>{!token && <div className="api-access-notice"><AlertTriangle size={16}/><span>Administrator OIDC token required. Event ingestion does not send notifications.</span></div>}<div className="form-grid scenario-inputs"><div className="field"><label htmlFor="hazardSource">Source name</label><input id="hazardSource" value={source} onChange={event => setSource(event.target.value)} placeholder="Agency/feed identifier" maxLength={120}/></div><div className="field"><label htmlFor="hazardSourceId">Source event ID</label><input id="hazardSourceId" value={sourceEventId} onChange={event => setSourceEventId(event.target.value)} maxLength={160}/></div><div className="field"><label htmlFor="hazardKind">Event type</label><select id="hazardKind" value={eventType} onChange={event => setEventType(event.target.value)}><option>EARTHQUAKE_OBSERVATION</option><option>EARTHQUAKE_HAZARD_ASSESSMENT</option><option>OFFICIAL_WARNING</option><option>FLOOD_FORECAST</option><option>FLOOD_OBSERVED</option></select></div><div className="field"><label htmlFor="hazardSeverity">Severity</label><select id="hazardSeverity" value={severity} onChange={event => setSeverity(event.target.value)}><option>LOW</option><option>MODERATE</option><option>HIGH</option><option>CRITICAL</option></select></div><div className="field"><label htmlFor="hazardZones">Target zones</label><select id="hazardZones" multiple value={targetZoneIds} onChange={event => setTargetZoneIds([...event.target.selectedOptions].map(option => option.value))}>{zones.map(zone => <option key={zone.id} value={zone.id}>{zone.id} · {zone.name}</option>)}</select></div><div className="field"><label htmlFor="hazardConfidence">Confidence (0–1, optional)</label><input id="hazardConfidence" type="number" min="0" max="1" step="0.05" value={confidence} onChange={event => setConfidence(event.target.value)}/></div><div className="field"><label htmlFor="hazardEventTime">Event time</label><input id="hazardEventTime" type="datetime-local" value={eventTime} onChange={event => setEventTime(event.target.value)}/></div><div className="field"><label htmlFor="hazardObservedAt">Observed at</label><input id="hazardObservedAt" type="datetime-local" value={observedAt} onChange={event => setObservedAt(event.target.value)}/></div><div className="field"><label htmlFor="hazardExpiresAt">Expires at</label><input id="hazardExpiresAt" type="datetime-local" value={expiresAt} onChange={event => setExpiresAt(event.target.value)}/></div></div><div className="request-actions"><button className="btn btn-primary" onClick={() => void submitSourceEvent()} disabled={!token || loading || !source.trim() || !sourceEventId.trim() || !targetZoneIds.length}>Submit for review</button></div></section>
    <section className="panel"><div className="panel-head"><div><h2>Hazard review queue</h2><p>Submitted events remain inactive until independently reviewed.</p></div><button className="btn btn-secondary" onClick={() => void refresh()} disabled={loading}><RefreshCw size={14}/>Refresh</button></div><div className="field alert-review-reason"><label htmlFor="alertReviewReason">Review / acknowledgement reason</label><input id="alertReviewReason" value={reason} onChange={event => setReason(event.target.value)} maxLength={500}/></div>{pending.length ? <div className="request-list">{pending.map(event => eventCard(event, true))}</div> : <div className="empty-state">No pending hazard events.</div>}</section>
    <section className="panel"><div className="panel-head"><div><h2>Active alerts</h2><p>Validated and unexpired source events; no SMS/email provider is configured.</p></div><span className="pending-badge">{active.length} active</span></div>{error && <div className="api-access-notice"><AlertTriangle size={16}/><span>{error}</span></div>}{active.length ? <div className="request-list">{active.map(event => eventCard(event))}</div> : <div className="empty-state">No validated active alerts.</div>}</section>
  </>;
}