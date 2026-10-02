"""Report exporters: self-contained HTML (with plots), CSV, JSON."""
from __future__ import annotations

import base64
import csv
import datetime as _dt
import html
import json
from pathlib import Path

from ..core.models import Product
from ..core.results import Report
from ..core.units import fmt_freq

STATUS_COLORS = {"PASS": "#2a9d5c", "MARGINAL": "#e0a100", "FAIL": "#c0392b", "INFO": "#5a6b7b"}


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def export_html(report: Report, product: Product, path, include_plots: bool = True) -> Path:
    path = Path(path)
    rows = []
    for f in report.findings:
        rows.append(
            f"<tr><td><span class='st' style='background:{STATUS_COLORS.get(f.status)}'>{f.status}</span></td>"
            f"<td>{_e(f.title)}</td><td>{_e(f.standard)}</td>"
            f"<td class='num'>{'' if f.margin_db is None else f'{f.margin_db:+.1f}'}</td>"
            f"<td>{'' if not f.worst_freq_hz else fmt_freq(f.worst_freq_hz)}</td><td>{_e(f.detail)}</td></tr>")
    plots = []
    if include_plots:
        from .plotting import finding_png
        for i, f in enumerate(report.findings):
            if not f.traces:
                continue
            b64 = base64.b64encode(finding_png(f)).decode()
            plots.append(f"<figure><img alt='{_e(f.title)}' src='data:image/png;base64,{b64}'/>"
                         f"<figcaption>{_e(f.title)} - {_e(f.standard)}</figcaption></figure>")
    mit = []
    for m in report.mitigations:
        mit.append(f"<tr><td class='num'>P{m.priority}</td><td><b>{_e(m.title)}</b><br><small>{_e(m.rationale)}</small>"
                   f"</td><td>{_e(m.applies_to)}</td><td>{_e(m.category)}</td>"
                   f"<td>{_e(m.expected_improvement_db or '')}</td><td>{_e(m.effort)}</td></tr>")
    steps = []
    for s in report.next_steps:
        items = "".join(f"<li>{_e(a)}</li>" for a in s["actions"])
        steps.append(f"<h3>{_e(s['phase'])} &mdash; {_e(s['title'])}</h3><ul>{items}</ul>")
    c = report.counts()
    html_doc = f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>EMC assessment - {_e(product.name)}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1d2733;background:#fff;max-width:1200px}}
h1{{margin-bottom:0}} .sub{{color:#5a6b7b;margin-top:4px}}
table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}}
th,td{{border:1px solid #d5dbe1;padding:6px 8px;vertical-align:top;text-align:left}}
th{{background:#eef2f6}} .num{{text-align:right;white-space:nowrap}}
.st{{color:#fff;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600}}
.cards{{display:flex;gap:12px;flex-wrap:wrap}} .card{{border:1px solid #d5dbe1;border-radius:8px;padding:10px 16px}}
.card b{{font-size:22px;display:block}}
figure{{margin:12px 0;border:1px solid #e3e7eb;padding:8px;border-radius:6px}} img{{max-width:100%}}
figcaption{{font-size:12px;color:#5a6b7b}} .note{{font-size:12px;color:#5a6b7b}}
</style></head><body>
<h1>EMC assessment report</h1>
<p class='sub'>{_e(product.name)} &middot; {_e(product.platform)} {_e(product.system)} &middot;
Classification: {_e(product.classification)} &middot; generated {_dt.datetime.now():%Y-%m-%d %H:%M}</p>
<div class='cards'>
<div class='card'>Overall<b style='color:{STATUS_COLORS[report.overall]}'>{report.overall}</b></div>
<div class='card'>Fail<b>{c['FAIL']}</b></div><div class='card'>Marginal<b>{c['MARGINAL']}</b></div>
<div class='card'>Pass<b>{c['PASS']}</b></div><div class='card'>Info<b>{c['INFO']}</b></div></div>
<p><b>Design:</b> {_e(product.summary())}<br><b>Standards:</b> {_e(', '.join(report.standards) or '-')}</p>
<h2>Findings</h2>
<table><tr><th>Status</th><th>Check</th><th>Standard / reference</th><th>Margin dB</th><th>Worst f</th><th>Detail</th></tr>
{''.join(rows)}</table>
<h2>Recommended mitigations</h2>
<table><tr><th>Pri</th><th>Mitigation</th><th>Applies to</th><th>Category</th><th>Expected</th><th>Effort</th></tr>
{''.join(mit)}</table>
<h2>Next steps after prototype</h2>{''.join(steps)}
<h2>Plots</h2>{''.join(plots)}
<h2>Notes</h2><ul class='note'>{''.join(f'<li>{_e(n)}</li>' for n in report.notes)}</ul>
</body></html>"""
    path.write_text(html_doc, encoding="utf-8")
    return path


def export_csv(report: Report, path) -> Path:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["status", "check", "title", "standard", "subject", "margin_db", "worst_freq_hz", "detail"])
        for f in report.findings:
            w.writerow([f.status, f.check, f.title, f.standard, f.subject,
                        "" if f.margin_db is None else round(f.margin_db, 2), f.worst_freq_hz or "", f.detail])
        w.writerow([])
        w.writerow(["priority", "mitigation", "applies_to", "category", "expected", "effort", "rationale"])
        for m in report.mitigations:
            w.writerow([m.priority, m.title, m.applies_to, m.category, m.expected_improvement_db or "", m.effort,
                        m.rationale])
    return path


def export_json(report: Report, path) -> Path:
    path = Path(path)
    data = {
        "product": report.product_name, "overall": report.overall, "standards": report.standards,
        "findings": [{k: getattr(f, k) for k in ("check", "title", "status", "margin_db", "worst_freq_hz",
                                                   "standard", "subject", "detail")} for f in report.findings],
        "mitigations": [m.__dict__ for m in report.mitigations],
        "next_steps": report.next_steps, "notes": report.notes,
    }
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path
