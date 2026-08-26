#!/usr/bin/env python3
"""Panel Pro Pi: cada apertura/actualización lee journalctl en la Pi por SSH."""

from __future__ import annotations

import html
import json
import os
import sys
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deploy.pi_log_intel import collect_hits, load_config, owner_ips, owner_telegram_ids  # noqa: E402
from deploy.pi_panel import PiSSH, _services, _status_map  # noqa: E402

OUT_HTML = ROOT / "panel_pi_pro.html"
DEFAULT_PORT = 8765


def _origin_label(origin: str) -> str:
    return {
        "owner": "Tú",
        "other": "Otro usuario",
        "foreign": "IP ajena",
        "unknown": "Sin identificar",
    }.get(origin, origin)


def _origin_css(origin: str) -> str:
    return {
        "owner": "badge-ok",
        "other": "badge-warn",
        "foreign": "badge-warn",
        "unknown": "badge-muted",
    }.get(origin, "badge-muted")


def _detail_block(h) -> str:
    lines: list[str] = []
    if h.audit:
        a = h.audit
        lines.extend(
            [
                f"Usuario Telegram: {h.tg_user or '?'}  (id {h.tg_uid or '?'})",
                f"Origen: {_origin_label(h.origin)}",
                f"Acción: {a.get('action', '?')}",
                f"Fase: {a.get('phase', '?')}  (in=entrada, out=respuesta, err=error)",
                "",
            ]
        )
        if a.get("in"):
            lines.extend(["── ENVIÓ / PIDIÓ ──", str(a.get("in")), ""])
        if a.get("out"):
            lines.extend(["── RESPUESTA BOT ──", str(a.get("out")), ""])
    else:
        lines.append(f"Tipo: {h.kind} · Origen: {_origin_label(h.origin)}")
        if h.tg_uid:
            lines.append(f"Telegram id: {h.tg_uid}")
        if h.owner_ips:
            lines.append(f"IPs tuyas en línea: {', '.join(h.owner_ips)}")
        if h.foreign_ips:
            lines.append(f"IPs ajenas: {', '.join(h.foreign_ips)}")
        lines.append("")
    lines.extend(["── LOG COMPLETO ──", h.full])
    return html.escape("\n".join(lines))


def build_html(
    cfg: dict,
    statuses: dict[str, str],
    hits: list,
    *,
    view_mode: str = "all",
    hours: int = 6,
    fetch_error: str = "",
    is_live: bool = True,
) -> str:
    owners = sorted(owner_ips(cfg))
    tg_ids = sorted(owner_telegram_ids(cfg))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode_labels = {
        "all": "Todo (tú + otros + sistema)",
        "mine": "Solo tú",
        "others": "Solo otros usuarios",
        "foreign": "Solo IPs ajenas",
        "audit": "Solo auditoría detallada (in/out)",
    }
    mode = mode_labels.get(view_mode, mode_labels["all"])
    n_owner = sum(1 for h in hits if h.origin == "owner")
    n_other = sum(1 for h in hits if h.origin == "other")
    n_foreign = sum(1 for h in hits if h.origin == "foreign")

    rows = []
    for i, h in enumerate(hits):
        if h.tg_uid:
            user_show = (
                f'<span class="ip-mine">{html.escape(h.tg_user or str(h.tg_uid))}</span>'
                if h.origin == "owner"
                else f'<span class="uid-other">{html.escape(h.tg_user or str(h.tg_uid))}</span>'
            )
            user_show += f' <span class="ip-muted">#{h.tg_uid}</span>'
        elif h.foreign_ips:
            user_show = f'<span class="ip-foreign">{html.escape(", ".join(h.foreign_ips))}</span>'
        elif h.owner_ips:
            user_show = f'<span class="ip-mine">{html.escape(", ".join(h.owner_ips))}</span>'
        else:
            user_show = "—"

        rows.append(
            f"""
            <tr class="row-hit" data-kind="{html.escape(h.kind)}" data-unit="{html.escape(h.service)}" data-origin="{html.escape(h.origin)}">
              <td class="ts">{html.escape(h.ts or "—")}</td>
              <td><span class="svc">{html.escape(h.label)}</span></td>
              <td><span class="badge {_origin_css(h.origin)}">{html.escape(_origin_label(h.origin))}</span></td>
              <td>{user_show}</td>
              <td class="sum">{html.escape(h.summary)}</td>
              <td><button type="button" class="btn-sm" onclick="toggle({i})">Desplegar</button></td>
            </tr>
            <tr id="detail-{i}" class="detail hidden">
              <td colspan="6"><pre>{_detail_block(h)}</pre></td>
            </tr>
            """
        )

    svc_opts = ['<option value="all">Todos los servicios</option>']
    for unit, label in _services(cfg):
        st = statuses.get(unit, "?")
        svc_opts.append(
            f'<option value="{html.escape(unit)}">{html.escape(label)} ({html.escape(st)})</option>'
        )

    status_cards = ""
    for unit, label in _services(cfg):
        st = statuses.get(unit, "?")
        cls = "on" if st == "active" else "off"
        status_cards += f"""
        <div class="card-st {cls}">
          <div class="card-title">{html.escape(label)}</div>
          <div class="card-stat">{html.escape(st)}</div>
        </div>"""

    def _btn(mode_key: str, label: str, ghost: bool = False) -> str:
        cls = "btn btn-ghost" if ghost or view_mode != mode_key else "btn"
        if is_live:
            href = f"?mode={mode_key}&hours={hours}"
        else:
            href = f"javascript:alert('Usa PI_PANEL.cmd (sin argumentos) para modo vivo con actualización real')"
        return f'<a class="{cls}" href="{href}">{label}</a>'

    refresh_href = f"?mode={view_mode}&hours={hours}&t={int(time.time())}" if is_live else "#"
    live_badge = (
        '<span class="live">● EN VIVO — cada clic lee la Pi por SSH</span>'
        if is_live
        else '<span class="offline">⚠ Snapshot estático — ejecuta PI_PANEL.cmd para datos frescos</span>'
    )
    err_banner = (
        f'<div class="err">{html.escape(fetch_error)}</div>' if fetch_error else ""
    )
    empty_msg = (
        "Sin eventos en las últimas horas. Comprueba que la Pi responde por SSH "
        "y que los bots han tenido actividad."
        if not fetch_error
        else "No se pudieron leer logs."
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta http-equiv="Cache-Control" content="no-store"/>
<title>Panel Pi Pro</title>
<style>
:root {{
  --bg:#0f1419; --panel:#1a2332; --line:#2d3a4f; --text:#e7ecf3;
  --muted:#8b9cb3; --accent:#3b82f6; --ok:#22c55e; --warn:#f59e0b; --bad:#ef4444;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:15px/1.45 Segoe UI,system-ui,sans-serif; background:var(--bg); color:var(--text); }}
.wrap {{ max-width:1280px; margin:0 auto; padding:20px; }}
header {{ display:flex; flex-wrap:wrap; gap:16px; align-items:flex-start; justify-content:space-between; margin-bottom:20px; }}
h1 {{ margin:0; font-size:1.5rem; }}
.sub {{ color:var(--muted); font-size:.9rem; }}
.live {{ color:var(--ok); font-weight:600; font-size:.85rem; }}
.offline {{ color:var(--warn); font-weight:600; font-size:.85rem; }}
.err {{ background:#7f1d1d; color:#fecaca; padding:12px; border-radius:8px; margin:12px 0; }}
.toolbar {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; }}
.btn {{
  background:var(--accent); color:#fff; border:0; padding:10px 16px; border-radius:8px;
  font-weight:600; cursor:pointer; text-decoration:none; display:inline-block;
}}
.btn:hover {{ filter:brightness(1.1); }}
.btn-ghost {{ background:var(--panel); border:1px solid var(--line); color:var(--text); }}
.btn-sm {{ background:var(--panel); border:1px solid var(--line); color:var(--text); padding:4px 10px; border-radius:6px; cursor:pointer; font-size:.85rem; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:10px; margin:16px 0 24px; }}
.card-st {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px; }}
.card-st.on {{ border-color:#166534; }}
.card-st.off {{ border-color:#7f1d1d; opacity:.85; }}
.card-title {{ font-size:.78rem; color:var(--muted); margin-bottom:4px; }}
.card-stat {{ font-weight:700; text-transform:capitalize; }}
.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:16px; }}
.panel h2 {{ margin:0 0 12px; font-size:1.05rem; }}
.ips {{ font-family:Consolas,monospace; font-size:.85rem; color:var(--muted); }}
table {{ width:100%; border-collapse:collapse; font-size:.88rem; }}
th,td {{ padding:10px 8px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }}
th {{ color:var(--muted); font-weight:600; position:sticky; top:0; background:var(--panel); }}
.sum {{ max-width:420px; }}
.ts {{ white-space:nowrap; color:var(--muted); font-size:.82rem; }}
.badge {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:.75rem; font-weight:600; }}
.badge-warn {{ background:#78350f; color:#fde68a; }}
.badge-info {{ background:#1e3a5f; color:#bfdbfe; }}
.badge-ok {{ background:#14532d; color:#bbf7d0; }}
.badge-muted {{ background:#334155; color:#cbd5e1; }}
.uid-other {{ color:#fbbf24; font-weight:600; }}
.ip-foreign {{ color:var(--warn); font-weight:700; }}
.ip-mine {{ color:var(--ok); font-weight:600; }}
.ip-muted {{ color:var(--muted); font-size:.85rem; }}
.stats {{ display:flex; gap:16px; flex-wrap:wrap; margin:8px 0 0; }}
.stat {{ background:#0b1020; border:1px solid var(--line); border-radius:8px; padding:8px 14px; font-size:.9rem; }}
.stat b {{ color:var(--accent); }}
.detail pre {{ margin:0; padding:12px; background:#0b1020; border-radius:8px; overflow:auto; font-size:.8rem; white-space:pre-wrap; word-break:break-word; max-height:320px; }}
.hidden {{ display:none; }}
.filter {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:12px; align-items:center; }}
select, input[type=search] {{
  background:#0b1020; border:1px solid var(--line); color:var(--text);
  padding:8px 10px; border-radius:8px; min-width:160px;
}}
.count {{ color:var(--muted); margin-left:auto; }}
.help {{ color:var(--muted); font-size:.85rem; line-height:1.5; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Panel Pi Pro</h1>
      <div class="sub">{live_badge}</div>
      <div class="sub">admin@{html.escape(cfg['host'])} · generado {html.escape(now)} · últimas <b>{hours}h</b></div>
      <div class="sub">{html.escape(mode)}</div>
      <div class="stats">
        <span class="stat"><b>{len(hits)}</b> eventos</span>
        <span class="stat"><b>{n_owner}</b> tuyos</span>
        <span class="stat"><b>{n_other}</b> otros usuarios</span>
        <span class="stat"><b>{n_foreign}</b> IPs ajenas</span>
      </div>
      <div class="ips">Tu Telegram id: {html.escape(", ".join(str(x) for x in tg_ids) or "?")} · IPs PC: {html.escape(", ".join(owners))}</div>
    </div>
    <div class="toolbar">
      {_btn("others", "Otros usuarios")}
      {_btn("all", "Todo", ghost=True)}
      {_btn("mine", "Solo tú", ghost=True)}
      {_btn("audit", "Auditoría", ghost=True)}
      {_btn("foreign", "IPs ajenas", ghost=True)}
      <a class="btn btn-ghost" href="{refresh_href}">↻ Actualizar ahora</a>
    </div>
  </header>
  {err_banner}

  <div class="grid">{status_cards}</div>

  <div class="panel">
    <h2>Filtros y periodo</h2>
    <div class="filter">
      <label>Horas atrás:
        <select id="f-hours" onchange="changeHours(this.value)">
          <option value="3"{" selected" if hours==3 else ""}>3 h</option>
          <option value="6"{" selected" if hours==6 else ""}>6 h</option>
          <option value="12"{" selected" if hours==12 else ""}>12 h</option>
          <option value="24"{" selected" if hours==24 else ""}>24 h</option>
          <option value="48"{" selected" if hours==48 else ""}>48 h</option>
        </select>
      </label>
      <select id="f-svc" onchange="applyFilter()">{''.join(svc_opts)}</select>
      <select id="f-origin" onchange="applyFilter()">
        <option value="">Todos los orígenes</option>
        <option value="owner"{" selected" if view_mode=="mine" else ""}>Tú</option>
        <option value="other"{" selected" if view_mode=="others" else ""}>Otro usuario</option>
        <option value="foreign"{" selected" if view_mode=="foreign" else ""}>IP ajena</option>
      </select>
      <select id="f-kind" onchange="applyFilter()">
        <option value="">Todos los tipos</option>
        <option value="audit"{" selected" if view_mode=="audit" else ""}>Auditoría (in/out)</option>
        <option value="telegram">Telegram API</option>
        <option value="activity">Actividad bot</option>
        <option value="maestro">Maestro</option>
        <option value="ssh">SSH</option>
      </select>
      <input type="search" id="f-q" placeholder="Buscar texto, user_id, URL…" oninput="applyFilter()"/>
      <span class="count" id="f-count"></span>
    </div>
    <p class="help">
      Solo se oculta el spam de <code>getUpdates</code> (polling cada 10 s). Todo lo demás — mensajes, MP3, errores, SSH — aparece aquí.
      Pulsa <strong>Desplegar</strong> en cada fila para el log completo. Con <code>[AUDIT]</code> desplegado verás literalmente qué enviaste y qué respondió el bot.
    </p>
  </div>

  <div class="panel">
    <h2>Eventos ({len(hits)})</h2>
    <div style="overflow:auto; max-height:70vh;">
      <table id="tbl">
        <thead>
          <tr>
            <th>Hora</th><th>Servicio</th><th>Origen</th><th>Usuario / IP</th><th>Resumen</th><th></th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows) if rows else f'<tr><td colspan="6">{html.escape(empty_msg)}</td></tr>'}
        </tbody>
      </table>
    </div>
  </div>
</div>
<script>
const VIEW_MODE = {json.dumps(view_mode)};
const IS_LIVE = {json.dumps(is_live)};

function toggle(i) {{
  const el = document.getElementById('detail-' + i);
  if (el) el.classList.toggle('hidden');
}}
function changeHours(h) {{
  if (!IS_LIVE) return;
  location.href = '?mode=' + VIEW_MODE + '&hours=' + h + '&t=' + Date.now();
}}
function applyFilter() {{
  const svc = document.getElementById('f-svc').value;
  const origin = document.getElementById('f-origin').value;
  const kind = document.getElementById('f-kind').value;
  const q = document.getElementById('f-q').value.toLowerCase();
  let n = 0;
  document.querySelectorAll('tr.row-hit').forEach(row => {{
    const k = row.dataset.kind || '';
    const o = row.dataset.origin || '';
    const text = row.textContent.toLowerCase();
    const detail = row.nextElementSibling;
    let ok = true;
    if (svc !== 'all' && row.dataset.unit !== svc) ok = false;
    if (origin && o !== origin) ok = false;
    if (kind && k !== kind) ok = false;
    if (q && !text.includes(q)) ok = false;
    row.style.display = ok ? '' : 'none';
    if (detail && detail.classList.contains('detail') && !ok) detail.classList.add('hidden');
    if (ok) n++;
  }});
  document.getElementById('f-count').textContent = n + ' visibles';
}}
applyFilter();
</script>
</body>
</html>"""


def _hits_for_mode(ssh, cfg: dict, view_mode: str, hours: int) -> list:
    kw = dict(hours=hours)
    if view_mode == "foreign":
        return collect_hits(ssh, cfg, foreign_only=True, **kw)
    if view_mode == "mine":
        return collect_hits(ssh, cfg, mine_only=True, **kw)
    if view_mode == "others":
        return collect_hits(ssh, cfg, others_only=True, **kw)
    if view_mode == "audit":
        return collect_hits(ssh, cfg, audit_only=True, **kw)
    return collect_hits(ssh, cfg, **kw)


def generate_report(
    *,
    view_mode: str = "all",
    hours: int | None = None,
    is_live: bool = True,
) -> tuple[Path, str]:
    cfg = load_config()
    h = hours or int(cfg.get("log_since_hours", 6))
    fetch_error = ""
    statuses: dict[str, str] = {}
    hits: list = []

    print(f"  Leyendo Pi ({cfg['host']}) — últimas {h} h, modo {view_mode}…", flush=True)
    t0 = time.time()
    try:
        ssh = PiSSH(cfg)
        ssh.connect()
        try:
            statuses = _status_map(ssh, [u for u, _ in _services(cfg)])
            hits = _hits_for_mode(ssh, cfg, view_mode, h)
        finally:
            ssh.close()
    except Exception as exc:
        fetch_error = f"Error SSH / lectura: {exc}"
        print(f"  [ERROR] {fetch_error}", flush=True)

    elapsed = time.time() - t0
    print(f"  Listo: {len(hits)} eventos en {elapsed:.1f}s", flush=True)

    html_text = build_html(
        cfg,
        statuses,
        hits,
        view_mode=view_mode,
        hours=h,
        fetch_error=fetch_error,
        is_live=is_live,
    )
    OUT_HTML.write_text(html_text, encoding="utf-8")
    return OUT_HTML, fetch_error


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        view_mode = qs.get("mode", ["all"])[0]
        if view_mode not in ("all", "mine", "foreign", "others", "audit"):
            view_mode = "all"
        hours_raw = qs.get("hours", [""])[0]
        hours = int(hours_raw) if str(hours_raw).isdigit() else None
        path, _err = generate_report(view_mode=view_mode, hours=hours, is_live=True)
        body = path.read_text(encoding="utf-8").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _port_free(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def serve(port: int = DEFAULT_PORT, *, initial_mode: str = "all", hours: int | None = None) -> None:
    if not _port_free(port):
        url = f"http://127.0.0.1:{port}/?mode={initial_mode}"
        if hours:
            url += f"&hours={hours}"
        print(f"Ya hay panel en {url} — abriendo navegador (Actualizar recarga datos).")
        webbrowser.open(url)
        return

    print("Conectando a la Pi y generando primera carga…", flush=True)
    generate_report(view_mode=initial_mode, hours=hours, is_live=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}/?mode={initial_mode}"
    if hours:
        url += f"&hours={hours}"
    print(f"\nPanel Pro EN VIVO: {url}")
    print("Cada Actualizar o cambio de filtro vuelve a leer journalctl en la Pi.")
    print("Deja esta ventana abierta. Ctrl+C para cerrar.\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")


def main() -> int:
    args = sys.argv[1:]
    mode = os.environ.get("PI_PANEL_MODE", "all")
    hours_env = os.environ.get("PI_LOG_HOURS", "")
    hours = int(hours_env) if hours_env.isdigit() else None

    if not args or args[0] in ("open", "web", "serve", "vivo"):
        port = DEFAULT_PORT
        if len(args) > 1 and args[-1].isdigit():
            port = int(args[-1])
        serve(port, initial_mode=mode, hours=hours)
        return 0
    if args[0] == "snapshot":
        path, err = generate_report(view_mode=mode, hours=hours, is_live=False)
        print(f"Snapshot: {path}" + (f" ({err})" if err else ""))
        webbrowser.open(path.as_uri())
        return 0
    for m in ("mine", "others", "audit", "foreign", "all", "todo"):
        if args[0] == m:
            serve(initial_mode=m if m != "todo" else "all", hours=hours)
            return 0
    if args[0] == "cli":
        os.execv(sys.executable, [sys.executable, str(ROOT / "deploy" / "pi_panel.py"), *args[1:]])
    print("Uso: pi_panel_pro.py [serve|snapshot|cli]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
