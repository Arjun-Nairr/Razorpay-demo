"""User-run proof: one persisted Case 3 you can inspect in Neon.

Talks ONLY to the already-running local API (existing endpoints). It does NOT
open the DB, hold credentials, force an outcome, or fall back to direct Gemini.

    python scripts/neon_proof.py                 # interactive, pauses for Neon
    python scripts/neon_proof.py --yes           # no pauses (offline smoke)
    python scripts/neon_proof.py --no-hermes     # skip the model step (offline)

Env: HERMES_API_BASE (default http://127.0.0.1:8000).

Sequence:
  1. create one demo case, print its ID
  2. pause so you can inspect the saved case in Neon BEFORE Hermes runs
     (sql/neon_demo_inspect.sql, blocks 1-2)
  3. run ONE real Hermes decision (POST /demo/step advance) and show the
     persisted AI_MODEL_RUN audit (block 3 in the SQL file)
  4. advance the remaining simulated outcome steps, each only when the case
     state permits it (guards against duplicate effects)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("HERMES_API_BASE", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 120


def _req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        print(f"  ! {method} {path} -> HTTP {e.code}: {detail}", file=sys.stderr)
        raise SystemExit(2)
    except urllib.error.URLError as e:
        print(f"  ! cannot reach API at {BASE} ({e.reason}). Start it first "
              "(scripts/run_demo.ps1 -Mode hermes).", file=sys.stderr)
        raise SystemExit(2)


def _pause(auto: bool, msg: str) -> None:
    if auto:
        print(f"  [--yes] {msg}")
        return
    input(f"\n>>> {msg}\n    press Enter to continue... ")


def _case(cid: str) -> dict:
    return _req("GET", f"/demo/case/{cid}")


def _kinds(view: dict) -> list[str]:
    return [r["kind"] for r in view.get("timeline", [])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="no interactive pauses")
    ap.add_argument("--no-hermes", action="store_true",
                    help="skip the model decision step (offline path check)")
    args = ap.parse_args()

    health = _req("GET", "/health")
    mode = health.get("mode")
    print(f"API: {BASE}  evidence_mode={health.get('evidence_mode')}  mode={mode}")
    if not args.no_hermes and mode != "hermes-runtime":
        print(f"  ! expected mode 'hermes-runtime' for the live proof (got {mode!r}). "
              "Start with scripts/run_demo.ps1 -Mode hermes, or pass --no-hermes.",
              file=sys.stderr)
        return 2

    # 1. create the case ---------------------------------------------------
    opened = _req("POST", "/demo/case")
    cid, obl = opened["case_id"], opened["obligation_id"]
    print(f"\n1) created demo case  id={cid}  obligation={obl}  "
          f"(evidence_mode={opened['evidence_mode']})")

    # 2. inspect BEFORE Hermes ------------------------------------------
    print("\n2) The case is now persisted. In the Neon SQL editor run "
          "sql/neon_demo_inspect.sql:")
    print("     - block 1  (every case: id / status / recovered amount)")
    print(f"     - block 2  with 'REPLACE_WITH_CASE_ID' -> '{cid}'  (audit timeline;")
    print("               you should see only INPUT_EVENT + SCHEDULED_ACTION so far)")
    _pause(args.yes, "inspect the pre-Hermes rows in Neon")

    if args.no_hermes:
        print("\n[--no-hermes] stopping before the model step.")
        return 0

    # 3. one real Hermes decision ------------------------------------
    st = _case(cid)["case"]["state"]
    if st != "active":
        print(f"\n3) case state is {st!r}, not 'active' - skipping the decision step.")
    else:
        print("\n3) running ONE real Hermes decision (POST /demo/step advance)...")
        r = _req("POST", "/demo/step", {"case_id": cid, "step": "advance"})
        run = r.get("run", {})
        print(f"   run: proposals={run.get('proposals')} "
              f"strategist_failures={run.get('strategist_failures')} "
              f"scheduled={run.get('scheduled')} blocked={run.get('blocked')}")
        view = _case(cid)
        runs = [x for x in view["timeline"] if x["kind"] == "AI_MODEL_RUN"]
        if runs:
            h = runs[-1]["detail"].get("hermes", {})
            print("   persisted AI_MODEL_RUN.detail.hermes:")
            for k in ("runtime_revision", "provider_model", "decision_action",
                      "confidence_band", "validation_result", "failure_category",
                      "tool_calls_used", "duration_ms"):
                if k in runs[-1]["detail"] or k in h:
                    print(f"     {k:18}= {h.get(k, runs[-1]['detail'].get(k))}")
            if h.get("evidence_returned"):
                print(f"     evidence_returned = {json.dumps(h['evidence_returned'])}")
        else:
            print("   (no AI_MODEL_RUN row - the strategist failure path was taken; "
                  "check block 3 for STRATEGIST_FAILURE)")
        print(f"\n   Re-run SQL block 3 with case id '{cid}' to see the same rows in Neon.")
    _pause(args.yes, "inspect the persisted Hermes decision in Neon (SQL block 3)")

    # 4. remaining simulated steps, each only when state permits ------
    print("\n4) advancing the remaining simulated outcome steps (guarded by state):")
    for step in ("retry_failed", "advance", "capture"):
        view = _case(cid)
        case, kinds = view["case"], _kinds(view)
        state = case["state"]
        if state in ("recovered", "escalated", "stopped"):
            print(f"   - case is terminal ({state}); stopping.")
            break
        if step == "retry_failed" and case.get("retry_outcome_recorded"):
            print("   - retry_failed: already recorded; skipping (no duplicate effect).")
            continue
        if step == "capture":
            has_link = any(
                i.get("action") == "CREATE_RECOVERY_LINK" and i.get("reference")
                for i in case.get("action_intents", [])
            )
            if not has_link:
                print("   - capture: no authorized recovery link yet; skipping.")
                continue
        try:
            out = _req("POST", "/demo/step", {"case_id": cid, "step": step})
        except SystemExit:
            print(f"   - {step}: rejected by the API (state guard). continuing.")
            continue
        new_state = _case(cid)["case"]["state"]
        print(f"   - {step:12} -> state={new_state}")

    final = _case(cid)["case"]
    print(f"\nDONE. case={cid} state={final['state']} "
          f"attribution={final.get('attribution')} "
          f"simulated_recovered_paise={final.get('recovered_minor', 0)}")
    print(f"View the full persisted trail in Neon: sql/neon_demo_inspect.sql "
          f"blocks 2-5 with case id '{cid}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
