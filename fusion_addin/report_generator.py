"""
ADIE — Autonomous Design Integrity Engine
report_generator.py — HTML violation report

PURPOSE:
    Generates a self-contained, styled HTML report from violations.json.
    Called by the Monitor Agent after each run.
    Output: data/violations_report.html  (open in any browser)

USAGE (standalone):
    python report_generator.py

AUTHOR: Aryn Gahlot | ADIE Project
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ADIE Violations Report — {design_name}</title>
  <style>
    :root {{
      --bg:        #0d1117;
      --surface:   #161b22;
      --border:    #30363d;
      --text:      #e6edf3;
      --muted:     #8b949e;
      --critical:  #f85149;
      --warning:   #d29922;
      --info:      #388bfd;
      --pass:      #3fb950;
      --accent:    #58a6ff;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      font-size: 14px;
      line-height: 1.6;
      padding: 32px 24px;
    }}
    header {{
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 8px;
    }}
    .logo {{
      font-size: 28px;
      font-weight: 700;
      color: var(--accent);
      letter-spacing: -0.5px;
    }}
    .logo span {{ color: var(--muted); font-weight: 400; font-size: 16px; }}
    h1 {{
      font-size: 18px;
      font-weight: 600;
      color: var(--text);
    }}
    .meta {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 28px;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin-bottom: 28px;
    }}
    .stat-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      text-align: center;
    }}
    .stat-card .count {{
      font-size: 32px;
      font-weight: 700;
      line-height: 1;
    }}
    .stat-card .label {{
      font-size: 12px;
      color: var(--muted);
      margin-top: 4px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .stat-card.critical .count {{ color: var(--critical); }}
    .stat-card.warning  .count {{ color: var(--warning);  }}
    .stat-card.info     .count {{ color: var(--info);     }}
    .stat-card.pass     .count {{ color: var(--pass);     }}
    .section-title {{
      font-size: 13px;
      font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.8px;
      margin-bottom: 12px;
    }}
    .violation-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-left: 4px solid var(--border);
      border-radius: 8px;
      padding: 16px 20px;
      margin-bottom: 12px;
      transition: border-color 0.15s;
    }}
    .violation-card.critical {{ border-left-color: var(--critical); }}
    .violation-card.warning  {{ border-left-color: var(--warning);  }}
    .violation-card.info     {{ border-left-color: var(--info);     }}
    .card-header {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
    }}
    .severity-badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 20px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .severity-badge.critical {{ background: rgba(248,81,73,0.15);  color: var(--critical); }}
    .severity-badge.warning  {{ background: rgba(210,153,34,0.15); color: var(--warning);  }}
    .severity-badge.info     {{ background: rgba(56,139,253,0.15); color: var(--info);     }}
    .rule-id {{ font-weight: 600; color: var(--accent); font-size: 15px; }}
    .body-name {{ color: var(--muted); font-size: 13px; }}
    .detail {{ color: var(--text); margin-bottom: 10px; }}
    .metrics {{
      display: flex;
      gap: 20px;
      flex-wrap: wrap;
    }}
    .metric {{
      background: rgba(255,255,255,0.04);
      border-radius: 6px;
      padding: 4px 12px;
      font-size: 12px;
    }}
    .metric .mlabel {{ color: var(--muted); margin-right: 4px; }}
    .metric .mval   {{ color: var(--text);  font-weight: 600; }}
    .metric .mval.bad {{ color: var(--critical); }}
    .metric .mval.ok  {{ color: var(--pass); }}
    .no-violations {{
      text-align: center;
      padding: 48px;
      color: var(--pass);
      font-size: 18px;
      font-weight: 600;
    }}
    .no-violations small {{ display: block; color: var(--muted); font-weight: 400; margin-top: 6px; font-size: 13px; }}
    footer {{
      margin-top: 40px;
      padding-top: 16px;
      border-top: 1px solid var(--border);
      color: var(--muted);
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <header>
    <div class="logo">ADIE <span>Autonomous Design Integrity Engine</span></div>
  </header>
  <h1>Violations Report — {design_name}</h1>
  <div class="meta">Generated: {timestamp} · Design: {design_name} · Total rules checked: {total_rules}</div>

  <div class="summary-grid">
    <div class="stat-card critical">
      <div class="count">{n_critical}</div>
      <div class="label">Critical</div>
    </div>
    <div class="stat-card warning">
      <div class="count">{n_warning}</div>
      <div class="label">Warning</div>
    </div>
    <div class="stat-card info">
      <div class="count">{n_info}</div>
      <div class="label">Info</div>
    </div>
    <div class="stat-card pass">
      <div class="count">{n_pass}</div>
      <div class="label">Rules&nbsp;OK</div>
    </div>
  </div>

  {body}

  <footer>
    ADIE · Developer: Aryn Gahlot, RCOEM Nagpur ·
    AI: Gemini 1.5 Flash · CAD: Autodesk Fusion 360
  </footer>
</body>
</html>
"""

_CARD_TEMPLATE = """\
<div class="violation-card {severity}">
  <div class="card-header">
    <span class="severity-badge {severity}">{severity_upper}</span>
    <span class="rule-id">{rule_id}</span>
    <span class="body-name">→ {body_name}</span>
  </div>
  <div class="detail">{violation_detail}</div>
  <div class="metrics">
    <div class="metric">
      <span class="mlabel">Actual</span>
      <span class="mval bad">{actual_value} {unit}</span>
    </div>
    <div class="metric">
      <span class="mlabel">Required</span>
      <span class="mval ok">≥ {required_value} {unit}</span>
    </div>
    <div class="metric">
      <span class="mlabel">Recorded</span>
      <span class="mval">{timestamp}</span>
    </div>
  </div>
</div>
"""


def generate_html_report(
    violations: list[dict],
    rules_index: dict,
    output_path: Path,
    design_name: str = "Unknown Design",
) -> Path:
    """
    Write violations report HTML.

    Args:
        violations   : list of violation dicts from Monitor
        rules_index  : {rule_id: rule_dict} for total-rules count
        output_path  : destination .html file
        design_name  : human-readable design name

    Returns output_path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    n_critical = sum(1 for v in violations if v.get("severity") == "critical")
    n_warning  = sum(1 for v in violations if v.get("severity") == "warning")
    n_info     = sum(1 for v in violations if v.get("severity") == "info")
    total_rules = len(rules_index)
    n_pass     = max(0, total_rules - len(violations))

    if violations:
        # Sort: critical → warning → info
        _order = {"critical": 0, "warning": 1, "info": 2}
        sorted_v = sorted(violations, key=lambda x: _order.get(x.get("severity", "info"), 3))

        cards = []
        for v in sorted_v:
            sev = v.get("severity", "info")
            cards.append(_CARD_TEMPLATE.format(
                severity       = sev,
                severity_upper = sev.upper(),
                rule_id        = v.get("rule_id", "?"),
                body_name      = v.get("body_name", "?"),
                violation_detail = v.get("violation_detail", ""),
                actual_value   = v.get("actual_value", ""),
                required_value = v.get("required_value", ""),
                unit           = v.get("unit", ""),
                timestamp      = v.get("timestamp", "")[:19].replace("T", " "),
            ))

        body = (
            '<div class="section-title">Active Violations</div>\n' +
            "\n".join(cards)
        )
    else:
        body = (
            '<div class="no-violations">✅ Design is fully compliant'
            '<small>All rules passed on last validation run.</small></div>'
        )

    html = _HTML_TEMPLATE.format(
        design_name  = design_name or "Unnamed Design",
        timestamp    = now,
        total_rules  = total_rules,
        n_critical   = n_critical,
        n_warning    = n_warning,
        n_info       = n_info,
        n_pass       = n_pass,
        body         = body,
    )

    output_path.write_text(html, encoding="utf-8")
    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    try:
        from config import CONFIG
        violations_path = CONFIG["violations_json"]
        rules_path      = CONFIG["rules_json"]
        output_path     = CONFIG["html_report"]

        violations = []
        if violations_path.exists():
            with open(violations_path, encoding="utf-8") as f:
                violations = json.load(f)

        rules_index = {}
        if rules_path.exists():
            with open(rules_path, encoding="utf-8") as f:
                rules = json.load(f)
            rules_index = {r["rule_id"]: r for r in rules if "rule_id" in r}

        out = generate_html_report(violations, rules_index, output_path, "Demo Design")
        print(f"Report written to: {out.resolve()}")

    except Exception as e:
        print(f"Error: {e}")
