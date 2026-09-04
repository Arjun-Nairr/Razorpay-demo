"""Minimal local Streamlit interface for the Case 3 recovery demo.

    streamlit run scripts/demo_ui.py

Talks only to the local FastAPI backend (default http://127.0.0.1:8000, override
with HERMES_API_BASE). All credentials stay server-side; this UI never signs or
holds a secret. Buttons are disabled while a request is in flight so a
double-click cannot double-submit.
"""

from __future__ import annotations

import os

import requests
import streamlit as st

API = os.environ.get("HERMES_API_BASE", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 90

st.set_page_config(page_title="Hermes recovery demo (Case 3)", layout="wide")
st.title("Hermes — AI revenue recovery (Case 3, insufficient funds)")
st.caption(
    "Everything here is SIMULATED. No real messages, charges, links, or account "
    "changes. Recovered value is simulated and labelled."
)

ss = st.session_state
ss.setdefault("case_id", "")
ss.setdefault("busy", False)


def _call(method: str, path: str, **kw):
    ss.busy = True
    try:
        r = requests.request(method, f"{API}{path}", timeout=TIMEOUT, **kw)
        if r.status_code >= 400:
            st.error(f"{method} {path} -> {r.status_code}: {r.json().get('detail', r.text)}")
            return None
        return r.json()
    except requests.RequestException as exc:
        st.error(f"cannot reach the API at {API} ({type(exc).__name__}). Is uvicorn running?")
        return None
    finally:
        ss.busy = False


mode = "unknown"
try:
    health = requests.get(f"{API}/health", timeout=5).json()
    mode = health.get("mode", "unknown")
    st.sidebar.success(
        f"API up · evidence_mode = {health.get('evidence_mode')} · mode = {mode}"
    )
    if mode == "live-gemini":
        st.sidebar.info("Proposals are real Gemini output. Payments/links are SIMULATED.")
    else:
        st.sidebar.warning("Offline: proposals are scripted, not a model call. Payments/links are SIMULATED.")
except Exception:
    st.sidebar.error("API not reachable")

# --- controls -------------------------------------------------------------

c1, c2 = st.columns(2)
with c1:
    if st.button("Start a fresh Case 3", disabled=ss.busy, use_container_width=True):
        out = _call("POST", "/demo/case")
        if out:
            ss.case_id = out["case_id"]
            st.success(f"opened {out['case_id']} for {out['obligation_id']}")

with c2:
    ss.case_id = st.text_input("Case id (paste to reopen a persisted case)", ss.case_id)

st.divider()
b1, b2, b3, b4 = st.columns(4)
disabled = ss.busy or not ss.case_id
if b1.button("Advance time", disabled=disabled, use_container_width=True):
    _call("POST", "/demo/step", json={"case_id": ss.case_id, "step": "advance"})
if b2.button("Inject failed retry", disabled=disabled, use_container_width=True):
    _call("POST", "/demo/step", json={"case_id": ss.case_id, "step": "retry_failed"})
if b3.button("Simulate recovery payment", disabled=disabled, use_container_width=True):
    _call("POST", "/demo/step", json={"case_id": ss.case_id, "step": "capture"})
if b4.button("Refresh", disabled=disabled, use_container_width=True):
    pass  # falls through to the render below

# --- render -------------------------------------------------------------

if ss.case_id:
    view = _call("GET", f"/demo/case/{ss.case_id}")
    if view:
        case = view["case"]
        timeline = view["timeline"]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("State", case["state"])
        m2.metric("Attribution", case.get("attribution") or "-")
        m3.metric("Simulated recovered (minor)", case.get("recovered_minor", 0))
        m4.metric("Cumulative wait (h)", case.get("total_wait_hours", 0))

        st.subheader("Case")
        st.json(case)

        proposals = [r for r in timeline if r["kind"] == "AI_PROPOSAL"]
        policies = [r for r in timeline if r["kind"] == "POLICY_DECISION"]
        model_runs = [r for r in timeline if r["kind"] == "AI_MODEL_RUN"]
        if proposals:
            label = ("Latest AI proposal (actual Gemini output)"
                     if mode == "live-gemini"
                     else "Latest proposal (scripted offline reasoning, no model call)")
            st.subheader(label)
            st.json(proposals[-1]["detail"])
        if policies:
            st.subheader("Latest deterministic policy decision")
            st.json(policies[-1]["detail"])
        if model_runs:
            st.subheader("Latest model-run metadata")
            st.json(model_runs[-1]["detail"])

        st.subheader("Audit timeline (chronological)")
        st.dataframe(
            [
                {"seq": r["seq"], "t": r["logical_time"], "kind": r["kind"],
                 "detail": r["detail"]}
                for r in timeline
            ],
            use_container_width=True,
            hide_index=True,
        )
