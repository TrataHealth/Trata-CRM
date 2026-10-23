"""Minimal NRCES FHIR R4 document bundles for ABDM health-information transfer."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

NRCES = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/"
COMPOSITION = {
    "DischargeSummary": ("DischargeSummaryRecord", "373942005", "Discharge summary"),
    "DiagnosticReport": ("DiagnosticReportRecord", "721981007", "Diagnostic studies report"),
    "OPConsultation": ("OPConsultRecord", "371530004", "Clinical consultation report"),
    "Prescription": ("PrescriptionRecord", "440545006", "Prescription record"),
    "Invoice": ("InvoiceRecord", "INVOICE", "Invoice"),
}
GENDER = {"M": "male", "F": "female", "O": "other", "T": "other"}


def _u() -> str:
    return f"urn:uuid:{uuid.uuid4()}"


def _iso(v: Any) -> str:
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return str(v) if v else datetime.now(timezone.utc).isoformat()


def _text(s: Optional[str]) -> Dict[str, Any]:
    return {"text": s or "—"}


def build_bundle(cc: Dict[str, Any], patient: Dict[str, Any], org: Dict[str, Any]) -> Dict[str, Any]:
    """cc = care-context doc with hi_type, record (snapshot), display, record_date."""
    hi, rec = cc["hi_type"], cc.get("record") or {}
    prof, code, title = COMPOSITION[hi]
    date = _iso(cc.get("record_date"))
    p_url, o_url, a_url, c_url = _u(), _u(), _u(), _u()
    entries: List[Dict[str, Any]] = []
    section: List[Dict[str, Any]] = []

    def add(res: Dict[str, Any], sec: bool = True) -> str:
        url = _u()
        res.setdefault("id", url.split(":")[-1])
        entries.append({"fullUrl": url, "resource": res})
        if sec:
            section.append({"reference": url})
        return url

    subj = {"reference": p_url, "display": patient.get("name")}
    if hi in ("DischargeSummary", "OPConsultation"):
        enc = {"resourceType": "Encounter", "status": "finished",
               "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                         "code": "IMP" if hi == "DischargeSummary" else "AMB",
                         "display": "inpatient encounter" if hi == "DischargeSummary" else "ambulatory"},
               "subject": subj, "period": {"start": _iso(rec.get("start") or cc.get("record_date")), "end": date}}
        add(enc)
        for label in ("final_diagnosis", "admission_diagnosis", "reason"):
            if rec.get(label):
                add({"resourceType": "Condition", "subject": subj, "code": _text(rec[label]),
                     "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]}})
        notes = "\n".join(f"{k.replace('_', ' ').title()}: {rec[k]}" for k in
                          ("treatment_given", "condition_at_discharge", "follow_up_instructions", "outcome_notes", "doctor") if rec.get(k))
        if notes:
            add({"resourceType": "DocumentReference", "status": "current", "subject": subj, "type": _text(title),
                 "content": [{"attachment": {"contentType": "text/plain", "data": _b64(notes), "title": title}}]})
    elif hi == "DiagnosticReport":
        obs = [add({"resourceType": "Observation", "status": "final", "code": _text(t), "subject": subj}, sec=False)
               for t in (rec.get("tests") or ["Investigation"])]
        dr = {"resourceType": "DiagnosticReport", "status": "final", "code": _text(rec.get("title") or "Laboratory report"),
              "subject": subj, "effectiveDateTime": date, "issued": date, "result": [{"reference": o} for o in obs],
              "performer": [{"reference": o_url}]}
        if rec.get("report_url"):
            dr["presentedForm"] = [{"contentType": "application/pdf", "url": rec["report_url"], "title": "Report"}]
        add(dr)
    elif hi == "Prescription":
        for line in rec.get("items") or ["As advised"]:
            add({"resourceType": "MedicationRequest", "status": "active", "intent": "order", "subject": subj,
                 "medicationCodeableConcept": _text(line), "authoredOn": date,
                 "dosageInstruction": [{"text": line}], "requester": {"reference": a_url}})
    elif hi == "Invoice":
        amt = float(rec.get("amount") or 0)
        add({"resourceType": "Invoice", "status": "issued" if rec.get("paid") is False else "balanced", "subject": subj,
             "date": date, "issuer": {"reference": o_url},
             "lineItem": [{"sequence": 1, "chargeItemCodeableConcept": _text(rec.get("description") or cc.get("display")),
                           "priceComponent": [{"type": "base", "amount": {"value": amt, "currency": "INR"}}]}],
             "totalNet": {"value": amt, "currency": "INR"}, "totalGross": {"value": amt, "currency": "INR"}})

    comp = {"resourceType": "Composition", "id": c_url.split(":")[-1], "meta": {"profile": [NRCES + prof]},
            "status": "final", "type": {"coding": [{"system": "http://snomed.info/sct", "code": code, "display": title}], "text": title},
            "subject": subj, "date": date, "author": [{"reference": a_url}], "custodian": {"reference": o_url},
            "title": f"{title} — {cc.get('display') or ''}".strip(" —"), "section": [{"title": title, "entry": section}]}
    pat = {"resourceType": "Patient", "id": p_url.split(":")[-1],
           "identifier": [{"system": "https://healthid.ndhm.gov.in", "value": patient.get("abha_number")}],
           "name": [{"text": patient.get("name")}], "gender": GENDER.get((patient.get("gender") or "")[:1].upper(), "unknown")}
    orgr = {"resourceType": "Organization", "id": o_url.split(":")[-1], "name": org.get("name") or "Trata Health",
            "identifier": [{"system": "https://facility.ndhm.gov.in", "value": org.get("hip_id")}]}
    auth = {"resourceType": "Practitioner", "id": a_url.split(":")[-1], "name": [{"text": rec.get("doctor") or org.get("name") or "Trata Health"}]}
    return {"resourceType": "Bundle", "id": str(uuid.uuid4()), "meta": {"profile": [NRCES + "DocumentBundle"], "lastUpdated": _iso(None)},
            "identifier": {"system": "https://trata.health/bundle", "value": cc["reference"]}, "type": "document",
            "timestamp": _iso(None),
            "entry": [{"fullUrl": c_url, "resource": comp}, {"fullUrl": p_url, "resource": pat},
                      {"fullUrl": o_url, "resource": orgr}, {"fullUrl": a_url, "resource": auth}, *entries]}


def _b64(s: str) -> str:
    import base64
    return base64.b64encode(s.encode()).decode()
