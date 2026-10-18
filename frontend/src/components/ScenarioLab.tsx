"use client";

import { useEffect, useState } from "react";
import { Activity, AlertTriangle, Play, RotateCcw } from "lucide-react";

type Zone = { id: string; name: string; score: number; exposure: number };
type InventoryItem = { resource: string; available: number };
type Recommendation = { zone_id: string; resource: string; requested: number; recommended: number; allocated: number; unmet: number; shortage: number; explanation: string };
type Simulation = { mode: string; committed: boolean; name: string; baseline_metrics: Record<string, number>; simulated_metrics: Record<string, number>; affected_zones: Array<Record<string, number | string>>; baseline_recommendations: { recommendations: Recommendation[] }; simulated_recommendations: { recommendations: Recommendation[] }; assumptions: string[]; unsupported_inputs: string[] };
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function ScenarioLab({ zones, inventory }: { zones: Zone[]; inventory: InventoryItem[] }) {
  const [name, setName] = useState("Flood exposure what-if");
  const [zoneId, setZoneId] = useState(zones[0]?.id ?? "");
  const [riskDelta, setRiskDelta] = useState("10");
  const [exposureMultiplier, setExposureMultiplier] = useState("1.25");
  const [resource, setResource] = useState(inventory[0]?.resource ?? "");
  const [availabilityReduction, setAvailabilityReduction] = useState("0");
  const [result, setResult] = useState<Simulation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (!zoneId && zones.length) setZoneId(zones[0].id); }, [zoneId, zones]);

  async function simulate() {
    setLoading(true);
    setError("");
    try {
      const reduction = Number(availabilityReduction);
      const response = await fetch(`${API}/api/scenarios/simulate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          exposure_multiplier: Number(exposureMultiplier),
          risk_score_delta: zoneId ? { [zoneId]: Number(riskDelta) } : {},
          resource_availability_reduction: resource && reduction ? { [resource]: reduction } : {},
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Scenario simulation failed");
      setResult(data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Scenario simulation failed");
    } finally {
      setLoading(false);
    }
  }

  return <>
    <section className="panel">
      <div className="panel-head"><div><h2>What-if inputs</h2><p>Changes are isolated from operational inventory and requests.</p></div><span className="pill-demo">SIMULATION ONLY</span></div>
      <div className="form-grid scenario-inputs">
        <div className="field"><label htmlFor="scenarioName">Scenario name</label><input id="scenarioName" value={name} onChange={event => setName(event.target.value)} maxLength={100}/></div>
        <div className="field"><label htmlFor="scenarioZone">Zone risk adjustment</label><select id="scenarioZone" value={zoneId} onChange={event => setZoneId(event.target.value)}>{zones.map(zone => <option key={zone.id} value={zone.id}>{zone.id} · {zone.name}</option>)}</select></div>
        <div className="field"><label htmlFor="scenarioRisk">Risk score delta</label><input id="scenarioRisk" type="number" min="-100" max="100" value={riskDelta} onChange={event => setRiskDelta(event.target.value)}/></div>
        <div className="field"><label htmlFor="scenarioExposure">Exposure multiplier</label><input id="scenarioExposure" type="number" min="0" max="10" step="0.05" value={exposureMultiplier} onChange={event => setExposureMultiplier(event.target.value)}/></div>
        <div className="field"><label htmlFor="scenarioResource">Resource availability</label><select id="scenarioResource" value={resource} onChange={event => setResource(event.target.value)}>{inventory.map(item => <option key={item.resource} value={item.resource}>{item.resource.replaceAll("_", " ")}</option>)}</select></div>
        <div className="field"><label htmlFor="scenarioReduction">Availability reduction (%)</label><input id="scenarioReduction" type="number" min="0" max="100" value={availabilityReduction} onChange={event => setAvailabilityReduction(event.target.value)}/></div>
      </div>
      <div className="request-actions"><button className="btn btn-primary" onClick={() => void simulate()} disabled={loading || !zones.length}><Play size={15}/>{loading ? "Simulating…" : "Run scenario"}</button><button className="btn btn-secondary" onClick={() => setResult(null)} disabled={!result}><RotateCcw size={15}/>Clear results</button></div>
      {error && <div className="error-banner"><AlertTriangle size={16}/>{error}</div>}
    </section>
    {result && <>
      <div className="workflow-banner"><Activity size={18}/><div><b>{result.name} · {result.mode}</b><p>Baseline and simulated estimates are reproducible assumptions, not forecasts. No operational state was changed.</p></div></div>
      <section className="panel"><div className="panel-head"><div><h2>Impact comparison</h2><p>Zone and exposure deltas from the submitted assumptions.</p></div></div><div className="table-scroll"><table><thead><tr><th>Metric</th><th>Baseline</th><th>Scenario</th></tr></thead><tbody>{Object.keys(result.baseline_metrics).map(key => <tr key={key}><td>{key.replaceAll("_", " ")}</td><td>{result.baseline_metrics[key]}</td><td>{result.simulated_metrics[key]}</td></tr>)}</tbody></table></div></section>
      <section className="panel"><div className="panel-head"><div><h2>Resource recommendations</h2><p>Existing pending request quantities ranked by the allocation engine.</p></div></div><div className="table-scroll"><table><thead><tr><th>Zone</th><th>Resource</th><th>Requested</th><th>Recommended</th><th>Allocated</th><th>Unmet</th><th>Shortage</th></tr></thead><tbody>{result.simulated_recommendations.recommendations.map((item, index) => <tr key={`${item.zone_id}-${item.resource}-${index}`} title={item.explanation}><td>{item.zone_id}</td><td>{item.resource.replaceAll("_", " ")}</td><td>{item.requested}</td><td>{item.recommended}</td><td>{item.allocated}</td><td>{item.unmet}</td><td>{item.shortage}</td></tr>)}</tbody></table></div><div className="scenario-notes"><b>Assumptions</b>{result.assumptions.map(item => <p key={item}>{item}</p>)}<b>Unsupported data</b>{result.unsupported_inputs.map(item => <p key={item}>{item}</p>)}</div></section>
    </>}
  </>;
}