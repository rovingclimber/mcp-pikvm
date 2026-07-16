from __future__ import annotations

import hmac
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from .config import _value
from .runtime_config import RuntimeConfig
from .security import ConfigurationError


_PAGE = """<!doctype html><html><head><meta charset=utf-8><title>PiKVM MCP admin</title><style>
body{font:16px system-ui,sans-serif;max-width:760px;margin:3rem auto;padding:0 1rem;color:#17202a}label{display:block;margin:1rem 0 .25rem}input{width:100%;box-sizing:border-box;padding:.6rem}button{margin-top:1.25rem;padding:.65rem 1rem}pre{background:#f4f6f7;padding:1rem;white-space:pre-wrap}.note{color:#566573}</style></head><body>
<h1>PiKVM MCP admin</h1><p class=note>This page is intended for local access. It never displays stored PiKVM credentials.</p>
<label>Admin token<input id=token type=password autocomplete=off></label><button onclick=loadStatus()>Check status</button><pre id=status>Enter the admin token, then check status.</pre>
<hr><h2>Configure PiKVM</h2><p class=note>Leave password and control secret blank to retain them after an initial configuration. A control secret is generated and shown once if none exists.</p>
<label>PiKVM URL<input id=url placeholder="https://192.168.1.50"></label><label>PiKVM username<input id=username value=admin></label><label>PiKVM password<input id=password type=password autocomplete=new-password></label><label>Operator control secret (optional)<input id=control type=password autocomplete=new-password></label>
<label><input id=screen type=checkbox style="width:auto"> Enable screen capture for MCP clients</label><button onclick=save()>Validate and apply</button><pre id=result></pre>
<script>
function headers(){return {'Content-Type':'application/json','Authorization':'Bearer '+document.getElementById('token').value}}
async function loadStatus(){let r=await fetch('/api/status',{headers:headers()});document.getElementById('status').textContent=await r.text()}
async function save(){let data={url:url.value,username:username.value,password:password.value,control_secret:control.value,screen_capture_enabled:screen.checked};let r=await fetch('/api/config',{method:'POST',headers:headers(),body:JSON.stringify(data)});document.getElementById('result').textContent=await r.text();password.value='';control.value='';loadStatus()}
</script></body></html>"""


def create_admin_app(runtime: RuntimeConfig) -> Starlette:
    token = _value("MCP_ADMIN_TOKEN")
    if len(token) < 32:
        raise ConfigurationError("MCP_ADMIN_TOKEN must be at least 32 characters.")

    async def authorised(request: Request) -> bool:
        header = request.headers.get("authorization", "")
        return header.startswith("Bearer ") and hmac.compare_digest(header[7:], token)

    async def page(_: Request) -> HTMLResponse:
        return HTMLResponse(_PAGE, headers={"Cache-Control": "no-store"})

    async def status(request: Request) -> JSONResponse:
        if not await authorised(request):
            return JSONResponse({"error": "authentication_required"}, 401, {"WWW-Authenticate": "Bearer"})
        return JSONResponse(runtime.status(), headers={"Cache-Control": "no-store"})

    async def configure(request: Request) -> JSONResponse:
        if not await authorised(request):
            return JSONResponse({"error": "authentication_required"}, 401, {"WWW-Authenticate": "Bearer"})
        try:
            payload: Any = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("Configuration must be a JSON object.")
            state, generated_secret = runtime.apply(payload)
            response: dict[str, Any] = {"ok": True, "status": state}
            if generated_secret:
                response["generated_control_secret"] = generated_secret
            return JSONResponse(response, headers={"Cache-Control": "no-store"})
        except (ConfigurationError, ValueError, TypeError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, 400, headers={"Cache-Control": "no-store"})

    return Starlette(routes=[Route("/", page), Route("/api/status", status), Route("/api/config", configure, methods=["POST"])])
