"""Dependency-free local browser client for the Living Streets slice."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
import os
import tempfile
from urllib.parse import urlsplit

from .actions import board, converse, deliver, inspect as inspect_object, move, purchase
from .interactions import enter_door
from .model import Actor, Movement, World
from .persistence import execute_once, load_snapshot, save_snapshot
from .runtime import advance_world
from .streets import build_street_world


@dataclass
class WebSession:
    world: World
    player_id: str = "merchant"
    snapshot_path: Path | None = None
    owns_snapshot_path: bool = False
    lock: RLock = field(default_factory=RLock, repr=False)


def _player(session: WebSession) -> Actor:
    return session.world.actors[session.player_id]


def _state(session: WebSession) -> dict:
    world = session.world
    player = _player(session)
    present = [
        {"id": actor.id, "name": actor.name, "location_id": actor.location_id}
        for actor in world.actors.values()
        if actor.location_id == player.location_id and actor.id != player.id and actor.traveling_to is None
    ]
    current_doors = [
        {
            "id": door.id,
            "origin_id": door.origin_id,
            "destination_id": door.destination_id,
            "open": door.open,
            "locked": door.locked,
        }
        for door in world.doors.values()
        if player.location_id in {door.origin_id, door.destination_id}
    ]
    current_objects = [
        {"id": obj.id, "name": obj.name, "place_id": obj.place_id, "actions": obj.actions}
        for obj in world.situated_objects.values()
        if obj.place_id == player.location_id
    ]
    journal = [
        {
            "id": event.id,
            "kind": event.kind,
            "at": event.at.isoformat(),
            "description": event.description,
        }
        for event in world.events[-40:]
        if player.id in event.actors or player.location_id in event.entities
    ]
    return {
        "now": world.now.isoformat(),
        "event_count": len(world.events),
        "player": {
            "id": player.id,
            "name": player.name,
            "location_id": player.location_id,
            "traveling_to": player.traveling_to,
            "money": player.money,
            "goods": {good_id: world.quantity_held(player.id, good_id) for good_id in world.goods},
            "journal": journal,
        },
        "places": [
            {
                "id": place.id,
                "name": place.name,
                "x": place.x,
                "y": place.y,
                "interior": place.is_interior,
            }
            for place in world.places.values()
            if place.id in world.runtime.get("street_district", {}).get("visitable_sites", ())
            or place.id in world.runtime.get("street_district", {}).get("street_nodes", ())
        ],
        "objects": current_objects,
        "doors": current_doors,
        "present_actors": present,
        "passenger_services": [
            {"asset_id": service[0], "boarding_place_id": service[1], "destination_id": service[2]}
            for service in world.runtime.get("passenger_services", ())
            if len(service) >= 3
            and service[1] == player.location_id
            and service[0] in world.transport_assets
            and world.transport_assets[service[0]].location_id == player.location_id
            and world.transport_assets[service[0]].available
        ],
        "markets": [
            {"id": market.id, "place_id": market.place_id, "goods": sorted(market.fixed_prices)}
            for market in world.markets.values()
            if market.place_id in world.places
            and market.place_id == player.location_id
        ],
    }


def _advance_player(world: World, hours: float) -> float:
    advance_world(world, hours)
    return hours


def _result_summary(result: object) -> dict | None:
    if result is None:
        return None
    if isinstance(result, Movement):
        return {
            "movement_id": result.id,
            "route_id": result.route_id,
            "destination_id": result.destination_id,
            "duration_hours": result.duration_hours,
        }
    if hasattr(result, "market_id") and hasattr(result, "total"):
        return {
            "market_id": result.market_id,
            "good_type_id": result.good_type_id,
            "quantity": result.quantity,
            "unit_price": result.unit_price,
            "total": result.total,
            "side": result.side,
        }
    if isinstance(result, dict):
        return result
    if hasattr(result, "snapshot_id") and hasattr(result, "schema_version"):
        return {
            "snapshot_id": result.snapshot_id,
            "schema_version": result.schema_version,
            "checksum": result.checksum,
            "event_count": result.event_count,
        }
    if isinstance(result, (list, tuple)):
        return list(result)
    return {"value": result}


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Redos — Living Streets</title>
<style>
:root { color-scheme: light; font-family: system-ui, sans-serif; }
body { margin: 0; background: #f4efe7; color: #2f2924; }
header { padding: 1rem; background: #3b3028; color: #fffaf2; }
main { display: grid; gap: 1rem; max-width: 62rem; margin: auto; padding: 1rem; }
#map { width: 100%; min-height: 20rem; background: #d8e5df; border: 2px solid #8a7564; border-radius: .6rem; }
.panel { background: #fffaf2; border: 1px solid #d4c6b7; border-radius: .6rem; padding: 1rem; }
.actions { display: flex; flex-wrap: wrap; gap: .45rem; }
button { border: 0; border-radius: .35rem; padding: .6rem .75rem; background: #7b3f2a; color: white; font-weight: 600; }
button.secondary { background: #526b68; } button:disabled { opacity: .45; }
small, #log { color: #675b51; } #log { white-space: pre-wrap; min-height: 3rem; }
.site { cursor: pointer; } .site text { font-size: 11px; pointer-events: none; }
</style></head><body>
<header><strong>Redos — The Living Streets</strong><div id="clock"></div></header>
<main>
<section class="panel"><svg id="map" viewBox="0 0 7 4" role="img" aria-label="Lower Manhattan street map"></svg></section>
<section class="panel"><div id="status"></div><div class="actions" id="quick"></div><div class="actions" id="system"></div></section>
<section class="panel"><h2>Here</h2><div id="here"></div><div class="actions" id="nearby"></div></section>
<section class="panel"><h2>Inventory and journal</h2><div id="inventory"></div><div id="journal"></div></section>
<section class="panel"><h2>Activity</h2><div id="log">Loading canonical world…</div></section>
</main>
<script>
let state;
const log = (value) => document.querySelector('#log').textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
async function api(path, options={}) {
  const response = await fetch(path, {headers: {'content-type': 'application/json'}, ...options});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'request failed');
  return body;
}
async function command(action, args={}) {
  try {
    const body = await api('/api/command', {method:'POST', body: JSON.stringify({command_id: crypto.randomUUID(), action, ...args})});
    log(body.result || body.state);
    state = body.state; render();
  } catch (error) { log(error.message); }
}
function render() {
  const p = state.player;
  document.querySelector('#clock').textContent = state.now;
  document.querySelector('#status').textContent = `${p.name} · ${p.location_id}${p.traveling_to ? ` → ${p.traveling_to}` : ''} · $${p.money.toFixed(2)} · ${state.event_count} causal events`;
  const map = document.querySelector('#map'); map.innerHTML = '';
  const byId = Object.fromEntries(state.places.map(place => [place.id, place]));
  state.places.forEach(place => {
    const x = place.x + 1.5, y = 2.4 - place.y;
    const circle = document.createElementNS('http://www.w3.org/2000/svg','circle'); circle.setAttribute('cx',x); circle.setAttribute('cy',y); circle.setAttribute('r',place.id === p.location_id ? '.13' : '.09'); circle.setAttribute('fill',place.id === p.location_id ? '#b4492f' : '#526b68'); circle.classList.add('site'); circle.onclick=()=>command('move',{destination_id:place.id}); map.appendChild(circle);
    const text = document.createElementNS('http://www.w3.org/2000/svg','text'); text.setAttribute('x',x+.12); text.setAttribute('y',y+.04); text.textContent=place.name; map.appendChild(text);
  });
  const here = state.present_actors.length ? state.present_actors.map(a=>a.name).join(', ') : 'No one else is here.';
  document.querySelector('#here').textContent = `People present: ${here}`;
  document.querySelector('#inventory').textContent = `Goods: ${Object.entries(p.goods).filter(([, quantity])=>quantity > 0).map(([good, quantity])=>`${good} ${quantity}`).join(', ') || 'empty'}`;
  document.querySelector('#journal').textContent = p.journal.length ? p.journal.map(e=>`${e.at} · ${e.description}`).join('\\n') : 'No local events yet.';
  document.querySelector('#nearby').innerHTML = '';
  state.objects.filter(o=>o.place_id===p.location_id).forEach(o=>{ const b=document.createElement('button'); b.className='secondary'; b.textContent=`Inspect ${o.name}`; b.onclick=()=>command('inspect',{object_id:o.id}); document.querySelector('#nearby').appendChild(b); });
  state.present_actors.forEach(a=>{ const b=document.createElement('button'); b.className='secondary'; b.textContent=`Speak to ${a.name}`; b.onclick=()=>command('converse',{listener_id:a.id, proposition:'street-life', content:'The neighborhood is alive.', truthful:true}); document.querySelector('#nearby').appendChild(b); });
  state.present_actors.forEach(a=>Object.entries(p.goods).filter(([, quantity])=>quantity > 0).forEach(([good, quantity])=>{ const b=document.createElement('button'); b.className='secondary'; b.textContent=`Deliver 1 ${good} to ${a.name}`; b.onclick=()=>command('deliver',{recipient_id:a.id,good_type_id:good,quantity:Math.min(1, quantity)}); document.querySelector('#nearby').appendChild(b); }));
  state.doors.forEach(door=>{ const b=document.createElement('button'); b.className='secondary'; b.textContent=`Enter ${door.destination_id === p.location_id ? door.origin_id : door.destination_id}`; b.onclick=()=>command('enter_door',{door_id:door.id}); document.querySelector('#nearby').appendChild(b); });
  const quick=document.querySelector('#quick'); quick.innerHTML='';
  const wait=document.createElement('button'); wait.textContent='Wait 1 hour'; wait.onclick=()=>command('wait',{hours:1}); quick.appendChild(wait);
  const market=state.markets.find(m=>m.place_id===p.location_id); if (market) { const buy=document.createElement('button'); buy.textContent='Buy 1 metal'; buy.onclick=()=>command('purchase',{market_id:market.id,good_type_id:'metals',quantity:1}); quick.appendChild(buy); }
  state.passenger_services.forEach(service=>{ const b=document.createElement('button'); b.className='secondary'; b.textContent=`Board ${service.asset_id} → ${service.destination_id}`; b.onclick=()=>command('board',{asset_id:service.asset_id,destination_id:service.destination_id}); quick.appendChild(b); });
  const system=document.querySelector('#system'); system.innerHTML='';
  ['save','reload','restart'].forEach(action=>{ const b=document.createElement('button'); b.className='secondary'; b.textContent=action[0].toUpperCase()+action.slice(1); b.onclick=()=>command(action); system.appendChild(b); });
}
api('/api/state').then(body=>{state=body; render();}).catch(error=>log(error.message));
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    server: "_RedosServer"

    def _write(self, status: int, body: object, content_type: str = "application/json") -> None:
        payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        with self.server.session.lock:
            if path == "/":
                self._write(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path in {"/api/state", "/v1/state"}:
                self._write(200, _state(self.server.session))
            else:
                self._write(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path not in {"/api/command", "/v1/command"}:
            self._write(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 64 * 1024:
                raise ValueError("invalid request size")
            request = json.loads(self.rfile.read(length))
            with self.server.session.lock:
                result = self._command(request)
                state = _state(self.server.session)
            self._write(200, {"result": _result_summary(result), "state": state})
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            self._write(400, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            self._write(500, {"error": f"internal error: {exc}"})

    def _command(self, request: dict) -> object:
        session = self.server.session
        world = session.world
        command_id = request.get("command_id")
        action = request.get("action")
        if not isinstance(command_id, str) or not command_id:
            raise ValueError("command_id is required")
        if action == "save":
            if session.snapshot_path is None:
                descriptor, filename = tempfile.mkstemp(prefix="redos-web-", suffix=".sqlite3")
                os.close(descriptor)
                session.snapshot_path = Path(filename)
                session.owns_snapshot_path = True
            return save_snapshot(world, session.snapshot_path)
        if action == "reload":
            if session.snapshot_path is None:
                raise ValueError("no saved snapshot exists")
            session.world = load_snapshot(session.snapshot_path)
            return {"reloaded": True, "snapshot_path": str(session.snapshot_path)}
        if action == "restart":
            session.world = build_street_world(seed=world.seed).world
            return {"restarted": True, "seed": session.world.seed}
        if action == "move":
            return execute_once(world, command_id, move, world, session.player_id, request["destination_id"])
        if action == "inspect":
            return execute_once(world, command_id, inspect_object, world, session.player_id, request["object_id"])
        if action == "converse":
            return execute_once(
                world,
                command_id,
                converse,
                world,
                session.player_id,
                request["listener_id"],
                request.get("proposition", "conversation"),
                request.get("content", "Hello."),
                truthful=bool(request.get("truthful", True)),
            )
        if action == "purchase":
            return execute_once(
                world,
                command_id,
                purchase,
                world,
                session.player_id,
                request["market_id"],
                request["good_type_id"],
                float(request["quantity"]),
            )
        if action == "board":
            return execute_once(world, command_id, board, world, session.player_id, request["asset_id"], request["destination_id"])
        if action == "deliver":
            return execute_once(
                world,
                command_id,
                deliver,
                world,
                session.player_id,
                request["recipient_id"],
                request["good_type_id"],
                float(request["quantity"]),
            )
        if action == "enter_door":
            return execute_once(world, command_id, enter_door, world, session.player_id, request["door_id"])
        if action == "wait":
            hours = float(request.get("hours", 1))
            return execute_once(world, command_id, _advance_player, world, hours)
        raise ValueError(f"unknown action {action!r}")


class _RedosServer(ThreadingHTTPServer):
    session: WebSession

    def server_close(self) -> None:
        snapshot_path = self.session.snapshot_path
        owns_snapshot_path = self.session.owns_snapshot_path
        super().server_close()
        if owns_snapshot_path and snapshot_path is not None:
            snapshot_path.unlink(missing_ok=True)


def create_server(
    *,
    world: World | None = None,
    player_id: str = "merchant",
    host: str = "127.0.0.1",
    port: int = 0,
    snapshot_path: str | Path | None = None,
) -> _RedosServer:
    """Create a local server; caller owns its lifecycle and may call shutdown."""
    session = WebSession(world or build_street_world(seed=0).world, player_id, Path(snapshot_path) if snapshot_path else None)
    if player_id not in session.world.actors:
        raise KeyError(player_id)
    server = _RedosServer((host, port), _Handler)
    server.session = session
    return server


def main() -> None:
    server = create_server()
    print(f"Redos Living Streets: http://{server.server_address[0]}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
