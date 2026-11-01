#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hotel Centro Huancayo — Generador automático del dashboard semanal de Google Ads.

Qué hace:
  1. Llama a la API de Windsor.ai y trae los datos de la última semana (lun-dom).
  2. Calcula los KPIs, detecta cortes de entrega y topes de presupuesto.
  3. Genera observaciones automáticas (reglas) y arma el HTML (index.html).
  4. Guarda un histórico (data/history.json) para el gráfico de tendencia.

Pensado para correr dentro de GitHub Actions una vez por semana.
La API key se lee de la variable de entorno WINDSOR_API_KEY (secreto del repo).
"""

import os
import json
import datetime as dt
from urllib.parse import urlencode
from urllib.request import urlopen, Request

# ----------------------------------------------------------------------------
# CONFIGURACIÓN  — ajusta estos valores si cambian
# ----------------------------------------------------------------------------
ACCOUNT_ID   = "367-928-7458"          # cuenta de Google Ads
CONNECTOR    = "google_ads"
BUDGET_CAP   = 40.0                     # tope de presupuesto diario en S/ (para detectar días topados)
CURRENCY     = "S/"
CLIENT_NAME  = "Hotel Centro Huancayo"
CAMPAIGN     = "1/10 Palabras Clave · Maximizar Conversiones"
API_BASE     = "https://connectors.windsor.ai"   # API de datos de Windsor.ai
API_KEY      = os.environ.get("WINDSOR_API_KEY", "")

HISTORY_PATH = "data/history.json"
OUTPUT_PATH  = "index.html"


# ----------------------------------------------------------------------------
# 1. FECHAS — última semana completa lunes a domingo
# ----------------------------------------------------------------------------
def last_week_range(today=None):
    today = today or dt.date.today()
    # lunes de esta semana
    monday_this = today - dt.timedelta(days=today.weekday())
    end   = monday_this - dt.timedelta(days=1)   # domingo pasado
    start = end - dt.timedelta(days=6)            # lunes pasado
    return start, end


# ----------------------------------------------------------------------------
# 2. LLAMADAS A WINDSOR.AI
# ----------------------------------------------------------------------------
def windsor_get(fields, date_from, date_to):
    if not API_KEY:
        raise SystemExit("Falta WINDSOR_API_KEY (configúralo como secreto del repo).")
    params = {
        "api_key": API_KEY,
        "connector": CONNECTOR,
        "accounts": ACCOUNT_ID,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "fields": ",".join(fields),
        "_renderer": "json",
    }
    url = f"{API_BASE}/{CONNECTOR}?" + urlencode(params)
    req = Request(url, headers={"User-Agent": "dashboard-bot/1.0"})
    with urlopen(req, timeout=120) as r:
        payload = json.loads(r.read().decode("utf-8"))
    # Windsor devuelve {"data": [...]}
    return payload.get("data", payload if isinstance(payload, list) else [])


def num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------------------
# 3. AGREGADOS
# ----------------------------------------------------------------------------
def summarize(daily, devices, regions):
    imp = sum(num(r.get("impressions")) for r in daily)
    clk = sum(num(r.get("clicks")) for r in daily)
    sp  = sum(num(r.get("spend")) for r in daily)
    cv  = sum(num(r.get("conversions")) for r in daily)
    return {
        "impressions": imp,
        "clicks": clk,
        "spend": sp,
        "conversions": cv,
        "ctr": (clk / imp * 100) if imp else 0,
        "cpc": (sp / clk) if clk else 0,
        "cost_conv": (sp / cv) if cv else 0,
        "conv_clic": (cv / clk * 100) if clk else 0,
    }


def build_observations(daily, s, devices):
    """Observaciones automáticas por reglas (puedes editarlas antes de publicar)."""
    obs = []
    spends = [num(r.get("spend")) for r in daily]
    days_active = sum(1 for x in spends if x > 0)
    zero_days = sum(1 for x in spends if x == 0)

    if zero_days:
        obs.append(("red", "Interrupción de entrega",
                    f"Hubo {zero_days} día(s) sin entrega en la semana. "
                    f"Se va a revisar el medio de pago/estado de la campaña para evitar recurrencia."))

    capped = sum(1 for x in spends if x >= BUDGET_CAP * 0.98)
    if capped:
        obs.append(("warn", "Campaña topando presupuesto",
                    f"{capped} día(s) alcanzaron el tope de ~{CURRENCY}{BUDGET_CAP:.0f}. "
                    f"Se va a evaluar un ajuste del presupuesto diario para no perder volumen."))

    obs.append(("green", "Eficiencia de conversión",
                f"Costo por conversión de {CURRENCY}{s['cost_conv']:.2f} con {s['conversions']:.0f} "
                f"conversiones y CPC de {CURRENCY}{s['cpc']:.2f}."))

    # dispositivo
    dmap = {d.get("device"): d for d in devices}
    if "MOBILE" in dmap and "DESKTOP" in dmap:
        mc = num(dmap["MOBILE"].get("clicks")); dc = num(dmap["DESKTOP"].get("clicks"))
        total = mc + dc
        if total:
            obs.append(("teal", "Mix por dispositivo",
                        f"Mobile = {mc/total*100:.0f}% de los clics; desktop = {dc/total*100:.0f}%. "
                        f"Se va a monitorear el ajuste de puja por dispositivo."))
    return obs[:6]


# ----------------------------------------------------------------------------
# 4. HISTÓRICO (para el gráfico de tendencia)
# ----------------------------------------------------------------------------
def load_history():
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(hist):
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# 5. HTML
# ----------------------------------------------------------------------------
def build_html(start, end, daily, s, devices, regions, obs, hist):
    labels = [r.get("date", "")[5:] for r in daily]
    spend  = [round(num(r.get("spend")), 2) for r in daily]
    conv   = [round(num(r.get("conversions")), 1) for r in daily]

    regions_sorted = sorted(regions, key=lambda r: num(r.get("clicks")), reverse=True)[:6]
    reg_labels = [r.get("region", "—") for r in regions_sorted]
    reg_clicks = [int(num(r.get("clicks"))) for r in regions_sorted]

    dmap = {d.get("device"): d for d in devices}
    dev_labels, dev_clicks = [], []
    for key, name in (("MOBILE", "Mobile"), ("DESKTOP", "Desktop"), ("TABLET", "Tablet")):
        if key in dmap and num(dmap[key].get("clicks")) > 0:
            dev_labels.append(name); dev_clicks.append(int(num(dmap[key].get("clicks"))))

    trend_labels = [h["week"] for h in hist][-8:]
    trend_cpc    = [round(h["cpc"], 2) for h in hist][-8:]
    trend_cc     = [round(h["cost_conv"], 2) for h in hist][-8:]

    obs_html = "\n".join(
        f'<div class="obs {c}"><div class="n">{i+1:02d}</div><h4>{t}</h4><p>{d}</p></div>'
        for i, (c, t, d) in enumerate(obs)
    )

    period = f"{start.strftime('%d/%m')} – {end.strftime('%d/%m/%Y')}"
    generated = dt.date.today().strftime("%d/%m/%Y")

    return f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{CLIENT_NAME} — Reporte Semanal ({period})</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;900&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{{--bg:#0c1016;--card:#151b26;--border:#232c3b;--txt:#e7ecf3;--dim:#8b97a8;--faint:#5c677a;
--gold:#e8b64c;--teal:#43c9be;--blue:#5b9bff;--green:#54cf7c;--red:#ff6b6b;--warn:#ffab4d;
--mono:'JetBrains Mono',monospace;--sans:'DM Sans',system-ui,sans-serif;}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--txt);font-family:var(--sans);padding:32px 22px 64px;line-height:1.5}}
.wrap{{max-width:1180px;margin:0 auto}}
.head{{display:flex;justify-content:space-between;flex-wrap:wrap;gap:20px;margin-bottom:22px}}
.eyebrow{{font-family:var(--mono);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--gold)}}
h1{{font-size:28px;font-weight:900;letter-spacing:-.02em}}
.subtitle{{color:var(--dim);font-size:14px}}
.period{{text-align:right;font-family:var(--mono);font-size:12px;color:var(--dim)}}
.period .range{{font-size:15px;color:var(--txt);font-weight:700}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px}}
.kpi{{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px}}
.kpi .label{{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);margin-bottom:8px}}
.kpi .val{{font-size:26px;font-weight:900;font-family:var(--mono)}}
.section-title{{font-family:var(--mono);font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);margin:32px 0 14px;display:flex;align-items:center;gap:10px}}
.section-title::after{{content:"";flex:1;height:1px;background:var(--border)}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.panel{{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px}}
.panel h3{{font-size:14.5px;font-weight:700;margin-bottom:14px}}
.chart-box{{position:relative;height:260px}}
.tbl-wrap{{overflow-x:auto;border-radius:12px;border:1px solid var(--border)}}
table{{width:100%;border-collapse:collapse;font-size:13px;min-width:560px}}
thead th{{background:#11161f;font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);padding:11px 13px;text-align:right}}
thead th:first-child{{text-align:left}}
tbody td{{padding:11px 13px;text-align:right;font-family:var(--mono);border-top:1px solid rgba(35,44,59,.6)}}
tbody td:first-child{{text-align:left;font-family:var(--sans);font-weight:500}}
.obs-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.obs{{background:var(--card);border:1px solid var(--border);border-left:4px solid var(--gold);border-radius:12px;padding:16px 18px}}
.obs.red{{border-left-color:var(--red)}}.obs.warn{{border-left-color:var(--warn)}}
.obs.teal{{border-left-color:var(--teal)}}.obs.green{{border-left-color:var(--green)}}.obs.blue{{border-left-color:var(--blue)}}
.obs .n{{font-family:var(--mono);font-size:11px;color:var(--faint);font-weight:700}}
.obs h4{{font-size:14px;font-weight:700;margin:3px 0 7px}}
.obs p{{font-size:13px;color:var(--dim)}}
.foot{{margin-top:38px;padding-top:18px;border-top:1px solid var(--border);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;font-family:var(--mono);font-size:11px;color:var(--faint)}}
.foot span b{{color:var(--gold)}}
@media(max-width:900px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.grid-2,.obs-grid{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">

<div class="head">
  <div>
    <div class="eyebrow">Reporte Semanal · Google Ads</div>
    <h1>{CLIENT_NAME}</h1>
    <div class="subtitle">Campaña: {CAMPAIGN}</div>
  </div>
  <div class="period"><span class="range">{period}</span><br>Cuenta {ACCOUNT_ID} · {CURRENCY} (soles)</div>
</div>

<div class="kpis">
  <div class="kpi"><div class="label">Inversión</div><div class="val">{CURRENCY}{s['spend']:.2f}</div></div>
  <div class="kpi"><div class="label">Clics</div><div class="val">{s['clicks']:.0f}</div></div>
  <div class="kpi"><div class="label">Conversiones</div><div class="val">{s['conversions']:.0f}</div></div>
  <div class="kpi"><div class="label">Costo / Conv.</div><div class="val">{CURRENCY}{s['cost_conv']:.2f}</div></div>
</div>
<div class="kpis">
  <div class="kpi"><div class="label">CTR</div><div class="val">{s['ctr']:.2f}%</div></div>
  <div class="kpi"><div class="label">CPC</div><div class="val">{CURRENCY}{s['cpc']:.2f}</div></div>
  <div class="kpi"><div class="label">Impresiones</div><div class="val">{s['impressions']:.0f}</div></div>
  <div class="kpi"><div class="label">Conv / Clic</div><div class="val">{s['conv_clic']:.0f}%</div></div>
</div>

<div class="section-title">Evolución diaria</div>
<div class="grid-2">
  <div class="panel"><h3>Conversiones vs. Inversión</h3><div class="chart-box"><canvas id="chDaily"></canvas></div></div>
  <div class="panel"><h3>CPC y Costo/conv por semana</h3><div class="chart-box"><canvas id="chTrend"></canvas></div></div>
</div>

<div class="section-title">Segmentación</div>
<div class="grid-2">
  <div class="panel"><h3>Clics por dispositivo</h3><div class="chart-box"><canvas id="chDevice"></canvas></div></div>
  <div class="panel"><h3>Clics por provincia</h3><div class="chart-box"><canvas id="chProv"></canvas></div></div>
</div>

<div class="section-title">Observaciones y acciones</div>
<div class="obs-grid">{obs_html}</div>

<div class="foot">
  <span>Publicidad con <b>Diego</b> · No es magia. Son métricas.</span>
  <span>Datos: Google Ads vía Windsor.ai · Generado automáticamente el {generated}</span>
</div>

</div>
<script>
Chart.defaults.font.family="'DM Sans',sans-serif";Chart.defaults.color="#8b97a8";
const grid="rgba(35,44,59,.7)";
new Chart(chDaily,{{type:'line',data:{{labels:{json.dumps(labels)},datasets:[
  {{label:'Conversiones',data:{json.dumps(conv)},borderColor:'#54cf7c',backgroundColor:'rgba(84,207,124,.15)',fill:true,tension:.35,yAxisID:'y'}},
  {{label:'Inversión (S/)',data:{json.dumps(spend)},borderColor:'#e8b64c',tension:.35,yAxisID:'y1'}},
  {{label:'Tope ~{CURRENCY}{BUDGET_CAP:.0f}',data:{json.dumps([BUDGET_CAP]*len(labels))},borderColor:'rgba(255,107,107,.4)',borderDash:[5,4],pointRadius:0,yAxisID:'y1'}}
]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{labels:{{usePointStyle:true,boxWidth:8}}}}}},
  scales:{{y:{{position:'left',grid:{{color:grid}}}},y1:{{position:'right',grid:{{drawOnChartArea:false}},suggestedMax:{BUDGET_CAP+5}}}}}}}}});
new Chart(chTrend,{{type:'line',data:{{labels:{json.dumps(trend_labels)},datasets:[
  {{label:'CPC (S/)',data:{json.dumps(trend_cpc)},borderColor:'#5b9bff',tension:.3}},
  {{label:'Costo/conv (S/)',data:{json.dumps(trend_cc)},borderColor:'#ffab4d',tension:.3}}
]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{labels:{{usePointStyle:true,boxWidth:8}}}}}},scales:{{y:{{grid:{{color:grid}},beginAtZero:true}}}}}}}});
new Chart(chDevice,{{type:'bar',data:{{labels:{json.dumps(dev_labels)},datasets:[
  {{label:'Clics',data:{json.dumps(dev_clicks)},backgroundColor:['#43c9be','#e8b64c','#5b9bff'],borderRadius:6}}]}},
  options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{y:{{grid:{{color:grid}}}}}}}}}});
new Chart(chProv,{{type:'bar',data:{{labels:{json.dumps(reg_labels)},datasets:[
  {{label:'Clics',data:{json.dumps(reg_clicks)},backgroundColor:'#e8b64c',borderRadius:5}}]}},
  options:{{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{x:{{grid:{{color:grid}}}}}}}}}});
</script>
</body></html>"""


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    start, end = last_week_range()
    print(f"Generando reporte {start} → {end}")

    daily   = windsor_get(["date", "impressions", "clicks", "spend", "conversions",
                           "ctr", "average_cpc", "conversion_rate"], start, end)
    daily   = sorted(daily, key=lambda r: r.get("date", ""))
    devices = windsor_get(["device", "impressions", "clicks", "spend", "conversions"], start, end)
    regions = windsor_get(["region", "impressions", "clicks", "conversions", "spend"], start, end)

    s = summarize(daily, devices, regions)

    hist = load_history()
    week_label = f"{start.strftime('%d/%m')}"
    hist = [h for h in hist if h.get("week") != week_label]      # evita duplicar la misma semana
    hist.append({"week": week_label, "cpc": s["cpc"], "cost_conv": s["cost_conv"],
                 "conversions": s["conversions"], "spend": s["spend"]})
    hist = hist[-26:]                                            # guarda ~6 meses
    save_history(hist)

    obs = build_observations(daily, s, devices)
    html = build_html(start, end, daily, s, devices, regions, obs, hist)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"OK → {OUTPUT_PATH} ({len(html)} bytes)")


if __name__ == "__main__":
    main()
