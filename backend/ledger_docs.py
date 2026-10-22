"""Branded receipt / statement documents + emails for the provider ledger."""
from __future__ import annotations

import html as _html
import io
import os
from typing import Any, Dict, Optional

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "trata-logo.png")
LOGO_WEB_PATH = "/brand/trata-doc-logo.png"
MODES = {"bank_transfer": "Bank transfer (NEFT/RTGS/IMPS)", "upi": "UPI", "cheque": "Cheque", "cash": "Cash", "other": "Other"}

e = lambda v: _html.escape(str(v)) if v not in (None, "") else "—"  # noqa: E731
money = lambda v: f"Rs. {float(v or 0):,.2f}"  # noqa: E731
inr = lambda v: f"&#8377;{float(v or 0):,.2f}"  # noqa: E731


def pdf_bytes(doc_html: str) -> bytes:
    from xhtml2pdf import pisa
    buf = io.BytesIO()
    pisa.CreatePDF(doc_html, dest=buf, encoding="utf-8")
    return buf.getvalue()


BASE_CSS = """
@page { size: A4; margin: 14mm 12mm 16mm 12mm; }
body { font-family: Helvetica; font-size: 8.5pt; color: #091E42; }
.tag { font-size: 7.5pt; color: #5E6C84; }
.accent { background-color: #0B3D91; height: 3px; } .accent2 { background-color: #00B8A9; height: 3px; }
table { width: 100%; border-collapse: collapse; }
.box td { vertical-align: top; padding: 4px 6px; }
.h { font-size: 7pt; color: #5E6C84; text-transform: uppercase; letter-spacing: 1px; font-weight: bold; }
.items th { background-color: #F0F4FA; color: #42526E; font-size: 7pt; text-align: left; padding: 5px 4px; border-bottom: 1px solid #C1C7D0; }
.items td { padding: 5px 4px; border-bottom: 0.5px solid #DFE1E6; vertical-align: top; }
.r { text-align: right; } .c { text-align: center; } .mut { color: #6B778C; font-size: 7pt; }
.tot td { padding: 3px 6px; } .grand td { background-color: #0B3D91; color: #FFFFFF; font-size: 11pt; font-weight: bold; padding: 7px 6px; }
.stamp { color: #00875A; font-size: 14pt; font-weight: bold; }
.foot { font-size: 7pt; color: #6B778C; border-top: 0.5px solid #DFE1E6; padding-top: 6px; }
"""


def doc_header(title: str, sub_html: str) -> str:
    return (f'<table><tr><td width="55%"><img src="{LOGO_PATH}" width="190" height="69"/></td>'
            f'<td class="r" style="vertical-align:middle;"><span style="font-size:14pt;font-weight:bold;color:#0B3D91;">{title}</span><br/>{sub_html}</td>'
            '</tr></table><div class="accent"></div><div class="accent2"></div><br/>')


def seller_block(s: Dict[str, Any]) -> str:
    return (f'<div class="h">From</div><b>{e(s.get("legal_name"))}</b><br/>{e(s.get("address"))}<br/>'
            f'GSTIN: <b>{e(s.get("gstin"))}</b> &#183; PAN: {e(s.get("pan"))}<br/>{e(s.get("email"))}')


def render_receipt_html(inv: Dict[str, Any]) -> str:
    p = inv.get("payment") or {}
    s = inv.get("seller") or {}
    sub = (f'<span class="tag">Receipt # </span><b>{e(p.get("receipt_no"))}</b><br/>'
           f'<span class="tag">Received on {e(p.get("paid_on"))}</span>')
    return f"""<html><head><meta charset="utf-8"/><style>{BASE_CSS}</style></head><body>
{doc_header("PAYMENT RECEIPT", sub)}
<table class="box"><tr>
 <td width="50%">{seller_block(s)}</td>
 <td width="50%"><div class="h">Received from</div><b>{e(inv.get('provider_name'))}</b><br/>
   {e(inv.get('provider_address') or inv.get('provider_city'))}<br/>GSTIN: <b>{e(inv.get('provider_gstin'))}</b><br/>{e(inv.get('provider_email') or inv.get('provider_phone'))}</td>
</tr></table><br/>
<table class="items"><thead><tr><th>Against invoice</th><th>Billing period</th><th>Invoice date</th><th>Payment mode</th><th>Reference</th><th class="r">Amount received</th></tr></thead>
<tbody><tr><td><b>{e(inv.get('number'))}</b></td><td>{e(inv.get('month'))}</td><td>{e(inv.get('issue_date'))}</td>
<td>{e(MODES.get(p.get('mode'), p.get('mode')))}</td><td>{e(p.get('reference'))}</td><td class="r"><b>{money(p.get('amount'))}</b></td></tr></tbody></table><br/>
<table><tr><td width="55%" style="vertical-align:top;"><div class="h">Amount in words</div><b>{e(p.get('amount_words'))}</b>
 {('<br/><br/><div class="h">Note</div>' + e(p.get('note'))) if p.get('note') else ''}</td>
<td width="45%" style="vertical-align:top;"><table class="tot">
 <tr><td>Invoice total</td><td class="r">{money(inv.get('grand_total'))}</td></tr>
 <tr><td>Received</td><td class="r">{money(p.get('amount'))}</td></tr>
 <tr class="grand"><td>Balance on invoice</td><td class="r">{money(max(0.0, float(inv.get('grand_total') or 0) - float(p.get('amount') or 0)))}</td></tr>
</table><br/><div class="stamp r">PAYMENT RECEIVED</div></td></tr></table>
<br/><br/><div class="foot">Thank you for partnering with Trata Health. This is a computer-generated receipt from the Trata Health CRM and does not require a physical signature.</div>
</body></html>"""


def render_statement_html(st: Dict[str, Any]) -> str:
    s = st.get("seller") or {}
    rows = "".join(
        f"<tr><td>{e(x['date'])}</td><td>{e(x['type'].title())}</td><td>{e(x['ref'])}<br/><span class='mut'>{e(x['description'])}</span></td>"
        f"<td class='r'>{money(x['debit']) if x['debit'] else ''}</td><td class='r'>{money(x['credit']) if x['credit'] else ''}</td>"
        f"<td class='r'><b>{money(x['balance'])}</b></td></tr>" for x in st["entries"])
    period = f"{st.get('from') or 'Beginning'} to {st.get('to') or 'Today'}"
    sub = f'<span class="tag">Period </span><b>{e(period)}</b><br/><span class="tag">Generated {e(st["generated_on"])}</span>'
    return f"""<html><head><meta charset="utf-8"/><style>{BASE_CSS}</style></head><body>
{doc_header("ACCOUNT STATEMENT", sub)}
<table class="box"><tr><td width="50%">{seller_block(s)}</td>
<td width="50%"><div class="h">Statement for</div><b>{e(st.get('provider_name'))}</b><br/>{e(st.get('provider_city'))}<br/>GSTIN: <b>{e(st.get('provider_gstin'))}</b></td></tr></table>
<table class="box" style="background-color:#F7F9FC;"><tr>
 <td><span class="h">Opening balance</span><br/><b>{money(st['opening_balance'])}</b></td>
 <td><span class="h">Invoiced</span><br/><b>{money(st['total_debit'])}</b></td>
 <td><span class="h">Paid</span><br/><b>{money(st['total_credit'])}</b></td>
 <td><span class="h">Amount due</span><br/><b style="color:#BF2600;">{money(st['closing_balance'])}</b></td>
</tr></table><br/>
<table class="items"><thead><tr><th width="11%">Date</th><th width="10%">Type</th><th width="37%">Reference</th>
<th width="14%" class="r">Invoiced</th><th width="14%" class="r">Paid</th><th width="14%" class="r">Balance</th></tr></thead>
<tbody><tr><td colspan="5"><i>Opening balance</i></td><td class="r"><b>{money(st['opening_balance'])}</b></td></tr>{rows or "<tr><td colspan='6' class='c mut'>No activity in this period.</td></tr>"}
<tr class="grand"><td colspan="5">Closing balance (amount due)</td><td class="r">{money(st['closing_balance'])}</td></tr></tbody></table>
<br/><br/><div class="foot">Balance = invoices raised minus payments received. Void and draft invoices are excluded. Computer-generated statement from the Trata Health CRM.</div>
</body></html>"""


def email_shell(app_url: Optional[str], label: str, body: str) -> str:
    ok = bool(app_url and app_url.startswith("https://"))
    brand = (f'<img src="{e(app_url)}{LOGO_WEB_PATH}" alt="Trata Health" width="190" height="69" style="display:block;border:0"/>' if ok
             else '<div style="font-size:22px;font-weight:bold;color:#0B3D91">Trata Health</div>')
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F4F5F7;padding:24px 0">
<tr><td align="center"><table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;font-family:Arial,sans-serif;color:#091E42">
<tr><td style="padding:16px 24px 10px"><table role="presentation" width="100%"><tr><td>{brand}</td>
<td style="text-align:right;font-size:11px;color:#0B3D91;letter-spacing:1px;font-weight:bold">{label}</td></tr></table></td></tr>
<tr><td style="height:3px;background:#0B3D91"></td></tr><tr><td style="height:3px;background:#00B8A9"></td></tr>
<tr><td style="padding:24px">{body}
<p style="font-size:11px;color:#888;margin-top:24px">Sent by Trata Health billing. We never ask for passwords, OTPs or card details by email.
Questions? Reply to your Trata relationship manager.</p></td></tr></table></td></tr></table>"""


def receipt_email_html(inv: Dict[str, Any], app_url: Optional[str]) -> str:
    p = inv.get("payment") or {}
    rows = "".join(f"<tr><td style='padding:4px 0;color:#42526E'>{k}</td><td style='padding:4px 0;text-align:right'>{v}</td></tr>"
                   for k, v in (("Receipt #", e(p.get("receipt_no"))), ("Against invoice", e(inv.get("number"))),
                                ("Billing period", e(inv.get("month"))), ("Received on", e(p.get("paid_on"))),
                                ("Mode", e(MODES.get(p.get("mode"), p.get("mode")))), ("Reference", e(p.get("reference")))))
    link = (f'<p style="margin:20px 0"><a href="{e(app_url)}/provider/ledger" style="background:#0B3D91;color:#ffffff;'
            f'padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:bold">Download receipt</a></p>'
            if app_url and app_url.startswith("https://") else
            "<p>Sign in to your Trata provider console &rarr; Trata Patients &amp; Billing &rarr; Invoices to download the receipt PDF.</p>")
    body = f"""<h2 style="margin:0 0 8px;font-size:18px">Payment received &mdash; thank you</h2>
<p style="font-size:14px;line-height:20px">Hello {e(inv.get('provider_name'))},</p>
<p style="font-size:14px;line-height:20px">We have received your payment for invoice <b>{e(inv.get('number'))}</b>. Your branded receipt is ready in your console.</p>
<table role="presentation" width="100%" style="font-size:13px;border-top:1px solid #DFE1E6;border-bottom:1px solid #DFE1E6;margin:12px 0">{rows}
<tr><td style="padding:8px 0;font-weight:bold">Amount received</td><td style="padding:8px 0;text-align:right;font-weight:bold;font-size:16px;color:#006644">{inr(p.get('amount'))}</td></tr></table>{link}"""
    return email_shell(app_url, "PAYMENT RECEIPT", body)
