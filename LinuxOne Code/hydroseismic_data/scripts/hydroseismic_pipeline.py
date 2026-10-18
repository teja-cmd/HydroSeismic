#!/usr/bin/env python3
"""HydroSeismic USGS refresh and health monitor. No public warnings."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, tempfile
import requests
import pandas as pd

BASE = Path("/home/ibm-user/hydroseismic_data")
RAW, PROCESSED, OUT = BASE/"raw", BASE/"processed", BASE/"outputs"
SNAPSHOT = PROCESSED/"usgs_latest_refresh.csv"
RAW_FILE = RAW/"usgs_earthquakes_refresh.geojson"
STATUS = OUT/"hydroseismic_refresh_status.json"
REFRESH_HISTORY = OUT/"hydroseismic_refresh_history.jsonl"
MONITOR_HISTORY = OUT/"hydroseismic_monitor_history.jsonl"
HEALTH = OUT/"hydroseismic_health_check.json"
CONFIG = OUT/"hydroseismic_production_config.json"

def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
        raise

def append_jsonl(path, obj):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")
        f.flush()
        os.fsync(f.fileno())

def refresh():
    report = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "FAILED", "public_warnings_enabled": False
    }
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        if cfg.get("public_warnings_enabled") is not False:
            raise RuntimeError("Public warning safety gate failed.")

        url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
        response = requests.get(url, timeout=(10, 30),
            headers={"User-Agent": "HydroSeismic-monitor/1.0"})
        response.raise_for_status()
        payload = response.json()
        if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
            raise ValueError("Invalid USGS GeoJSON response.")

        rows = []
        for feature in payload["features"]:
            props = feature.get("properties") or {}
            geom = feature.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if len(coords) < 2 or not props.get("time") or not feature.get("id"):
                continue
            try:
                lon, lat = float(coords[0]), float(coords[1])
                mag = float(props["mag"])
                event_time = pd.to_datetime(props["time"], unit="ms", utc=True)
            except (TypeError, ValueError, KeyError, OverflowError):
                continue
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                continue
            if not pd.notna(mag) or pd.isna(event_time) or event_time > pd.Timestamp.now(tz="UTC"):
                continue
            rows.append({
                "incident_id": str(feature["id"]),
                "source": "USGS",
                "event_type": "earthquake",
                "latitude": lat,
                "longitude": lon,
                "magnitude": mag,
                "timestamp": event_time.isoformat(),
                "place": props.get("place") or "",
                "source_url": props.get("url") or ""
            })

        df = pd.DataFrame(rows, columns=[
            "incident_id", "source", "event_type", "latitude", "longitude",
            "magnitude", "timestamp", "place", "source_url"
        ])
        if df.empty:
            raise ValueError("No valid earthquake records received.")
        if df["incident_id"].duplicated().any():
            raise ValueError("Duplicate event IDs in response.")
        if not df["latitude"].between(-90, 90).all() or not df["longitude"].between(-180, 180).all():
            raise ValueError("Invalid coordinates in response.")

        # Prepare both files before replacing the CSV snapshot.
        csv_data = df.to_csv(index=False, lineterminator="\n")
        geojson_data = json.dumps(payload, separators=(",", ":")) + "\n"
        atomic_write(RAW_FILE, geojson_data)
        atomic_write(SNAPSHOT, csv_data)
        report.update({
            "status": "SUCCESS",
            "http_status": response.status_code,
            "records_received": len(payload["features"]),
            "records_saved": len(df),
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "snapshot_sha256": hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest(),
            "snapshot_path": str(SNAPSHOT)
        })
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_write(STATUS, json.dumps(report, indent=2) + "\n")
    append_jsonl(REFRESH_HISTORY, report)
    print("USGS refresh:", report["status"])
    if report.get("error"):
        print("Refresh error:", report["error"])
    else:
        print("Records saved:", report["records_saved"])
    return report

def monitor():
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "REVIEW_REQUIRED", "issues": [],
        "public_warnings_enabled": False
    }
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        if cfg.get("public_warnings_enabled") is not False:
            raise RuntimeError("Public warning safety gate failed.")
        refresh_report = json.loads(STATUS.read_text(encoding="utf-8"))
        df = pd.read_csv(SNAPSHOT)
        needed = ["incident_id", "latitude", "longitude", "magnitude", "timestamp"]
        if any(c not in df.columns for c in needed):
            raise ValueError("Snapshot schema is incomplete.")

        lat = pd.to_numeric(df.latitude, errors="coerce")
        lon = pd.to_numeric(df.longitude, errors="coerce")
        mag = pd.to_numeric(df.magnitude, errors="coerce")
        ts = pd.to_datetime(df.timestamp, errors="coerce", utc=True)
        retrieved = pd.to_datetime(refresh_report.get("retrieved_at_utc"), errors="coerce", utc=True)
        age = ((pd.Timestamp.now(tz="UTC") - retrieved).total_seconds()/60) if not pd.isna(retrieved) else None
        age = round(age, 2) if age is not None else None

        checks = {
            "refresh_succeeded": refresh_report.get("status") == "SUCCESS",
            "retrieval_age_minutes": age,
            "retrieval_recent": age is not None and 0 <= age <= 60,
            "rows": int(len(df)),
            "ids_unique": bool(df.incident_id.notna().all() and df.incident_id.astype(str).str.strip().ne("").all() and not df.incident_id.duplicated().any()),
            "coordinates_valid": bool(lat.notna().all() and lat.between(-90, 90).all() and lon.notna().all() and lon.between(-180, 180).all()),
            "timestamps_valid": bool(ts.notna().all() and (ts <= pd.Timestamp.now(tz="UTC")).all()),
            "magnitudes_present": bool(mag.notna().all()),
            "hash_matches": hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest() == refresh_report.get("snapshot_sha256")
        }
        ok = (
            checks["refresh_succeeded"] and checks["retrieval_recent"]
            and checks["rows"] > 0 and checks["ids_unique"]
            and checks["coordinates_valid"] and checks["timestamps_valid"]
            and checks["magnitudes_present"] and checks["hash_matches"]
        )
        result["checks"] = checks
        result["status"] = "HEALTHY" if ok else "REVIEW_REQUIRED"
        if not ok:
            result["issues"] = [k for k, v in checks.items() if v is False]
            if not checks["retrieval_recent"]:
                result["issues"].append("Refresh missing or older than 60 minutes")
    except Exception as exc:
        result["status"] = "ERROR"
        result["issues"].append(f"{type(exc).__name__}: {exc}")

    atomic_write(HEALTH, json.dumps(result, indent=2) + "\n")
    append_jsonl(MONITOR_HISTORY, result)
    print("HydroSeismic monitor:", result["status"])
    print("Issues:", result["issues"] or "None")
    print("Public warnings: DISABLED")
    return result

def main():
    refresh_report = refresh()
    health = monitor()
    print("FINAL PIPELINE STATUS")
    print("Refresh:", refresh_report["status"])
    print("Health:", health["status"])
    return 0 if refresh_report["status"] == "SUCCESS" and health["status"] == "HEALTHY" else 1

if __name__ == "__main__":
    raise SystemExit(main())
