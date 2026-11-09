"""Estrattore video Research API. Configurazione e guida in README_IT.md.

Nuovo punto di ingresso per python_tiktok-research-api di orsoFra.
Non importa gli script legacy; si può usare da solo o aggiungere al repository.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time

VIDEO_URL = "https://open.tiktokapis.com/v2/research/video/query/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
FILTERS = {"create_date", "username", "region_code", "video_id", "hashtag_name",
           "keyword", "music_id", "effect_id", "video_length", "view_count", "comment_count"}
FIELDS = set("id,video_description,create_time,region_code,share_count,view_count,like_count,comment_count,music_id,hashtag_names,username,effect_ids,playlist_id,voice_to_text,is_stem_verified,favorites_count,video_duration,hashtag_info_list,sticker_info_list,effect_info_list,video_mention_list,video_label,video_tag".split(","))


def validate(config):
    """Controlli locali; l'API resta l'autorità sulla validità dei filtri."""
    start = date.fromisoformat(config["start_date"])
    end = date.fromisoformat(config["end_date"])
    if start > end:
        raise ValueError("start_date deve precedere o coincidere con end_date")
    if end > datetime.now(timezone.utc).date():
        raise ValueError("end_date non può essere nel futuro")
    query = config["query"]
    if not isinstance(query, dict) or not query or set(query) - {"and", "or", "not"}:
        raise ValueError("query deve contenere liste and/or/not")
    if not any(query.values()):
        raise ValueError("Serve almeno una condizione")
    for conditions in query.values():
        if not isinstance(conditions, list):
            raise ValueError("and/or/not devono essere liste di condizioni")
        for c in conditions:
            if not isinstance(c, dict) or set(c) != {"operation", "field_name", "field_values"}:
                raise ValueError("Ogni condizione richiede operation, field_name, field_values")
            if c["field_name"] not in FILTERS:
                raise ValueError(f"Campo filtro sconosciuto: {c['field_name']}")
            if c["operation"] not in {"EQ", "IN", "GT", "GTE", "LT", "LTE"}:
                raise ValueError("Operatore non valido")
            values = c["field_values"]
            if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
                raise ValueError("field_values deve essere una lista non vuota di stringhe")
            if c["operation"] != "IN" and len(values) != 1:
                raise ValueError("Usare IN per più valori; gli altri operatori richiedono un valore")
    fields = config["fields"]
    if not isinstance(fields, list) or not fields or not all(isinstance(f, str) and f in FIELDS for f in fields):
        raise ValueError("fields deve essere una lista di campi video supportati")
    if "id" not in fields:
        raise ValueError("Includere id in fields per eliminare i duplicati")
    for name, lo, hi in [("max_count", 1, 100), ("max_requests", 1, 100000)]:
        if type(config[name]) is not int or not lo <= config[name] <= hi:
            raise ValueError(f"{name} deve essere un intero tra {lo} e {hi}")
    if config.get("is_random", False) is not False:
        raise ValueError("Questa versione usa is_random=false per la raccolta paginata")
    return start, end


def date_windows(start, end):
    """Finestre di 30 date UTC, estremi inclusi, senza buchi a fine mese."""
    while start <= end:
        stop = min(start + timedelta(days=29), end)
        yield start.strftime("%Y%m%d"), stop.strftime("%Y%m%d")
        start = stop + timedelta(days=1)


def make_body(config, start, end):
    return {"query": config["query"], "start_date": start, "end_date": end,
            "max_count": config["max_count"], "is_random": False}


class BudgetReached(Exception):
    pass


class Client:
    def __init__(self, key, secret, max_requests):
        import requests
        self.requests = requests
        self.session = requests.Session()
        self.key, self.secret = key, secret
        self.token, self.expiry = None, 0
        self.calls, self.max_requests = 0, max_requests

    def authenticate(self):
        r = self.session.post(TOKEN_URL, data={"client_key": self.key,
            "client_secret": self.secret, "grant_type": "client_credentials"}, timeout=60)
        if not r.ok:
            raise RuntimeError(f"Autenticazione fallita: HTTP {r.status_code}; verificare credenziali e accesso Research API")
        payload = r.json()
        if not payload.get("access_token"):
            raise RuntimeError("Autenticazione senza access_token: verificare autorizzazione Research API")
        self.token = payload["access_token"]
        self.expiry = time.monotonic() + max(1, int(payload["expires_in"]) - 60)

    def fetch(self, body, fields):
        refreshed = False
        for attempt in range(4):
            if self.calls >= self.max_requests:
                raise BudgetReached()
            if not self.token or time.monotonic() >= self.expiry:
                self.authenticate()
            self.calls += 1
            try:
                r = self.session.post(VIDEO_URL, params={"fields": ",".join(fields)},
                    headers={"Authorization": f"Bearer {self.token}"}, json=body, timeout=60)
            except (self.requests.Timeout, self.requests.ConnectionError):
                if attempt == 3:
                    raise RuntimeError("Connessione fallita dopo 4 tentativi") from None
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 401 and not refreshed:
                self.expiry = 0
                refreshed = True
                continue
            if r.status_code == 429:
                raise RuntimeError("HTTP 429: limite API raggiunto. Dati parziali conservati; riprovare più tardi")
            if 500 <= r.status_code < 600 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            if not r.ok:
                raise RuntimeError(f"Query fallita: HTTP {r.status_code}")
            result = r.json()
            error = result.get("error", {})
            if error.get("code") != "ok":
                raise RuntimeError(f"Errore TikTok: {error.get('code', 'assente')}; log_id={error.get('log_id', '')}")
            if not isinstance(result.get("data"), dict):
                raise RuntimeError("Risposta TikTok senza data")
            return result
        raise RuntimeError("Tentativi esauriti")


def collect(config, client, output):
    """Salva ogni pagina prima di proseguire; non confonde limiti e fine risultati."""
    start, end = validate(config)
    output.mkdir(parents=True, exist_ok=False)
    (output / "pages").mkdir()
    (output / "config_usata.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
               "unique_videos": 0, "pages": 0, "completed_windows": 0}
    seen = set()
    try:
        with (output / "videos.jsonl").open("w", encoding="utf-8") as stream:
            for first, last in date_windows(start, end):
                body = make_body(config, first, last)
                summary["active_window"] = [first, last]
                cursors = set()
                while True:
                    result = client.fetch(body, config["fields"])
                    summary["pages"] += 1
                    page = {"collected_at_utc": datetime.now(timezone.utc).isoformat(),
                            "request": body, "response": result}
                    (output / "pages" / f"{summary['pages']:06d}.json").write_text(
                        json.dumps(page, ensure_ascii=False, indent=2), encoding="utf-8")
                    data = result["data"]
                    videos = data.get("videos")
                    if not isinstance(videos, list) or type(data.get("has_more")) is not bool:
                        raise RuntimeError("Risposta inattesa: videos/has_more assenti o non validi; pagina salvata")
                    for video in videos:
                        if not isinstance(video, dict) or "id" not in video:
                            raise RuntimeError("Video senza id; pagina salvata")
                        identifier = str(video["id"])
                        if identifier not in seen:
                            seen.add(identifier)
                            stream.write(json.dumps(video, ensure_ascii=False) + "\n")
                            summary["unique_videos"] += 1
                    stream.flush()
                    print(f"{first}–{last}: pagina {summary['pages']}, video unici {summary['unique_videos']}")
                    if not data["has_more"]:
                        summary["completed_windows"] += 1
                        break
                    cursor, search_id = data.get("cursor"), data.get("search_id")
                    if type(cursor) is not int or cursor < 0 or not isinstance(search_id, str) or not search_id:
                        raise RuntimeError("Paginazione incompleta: mancano cursor/search_id validi")
                    if cursor in cursors or cursor <= body.get("cursor", -1):
                        raise RuntimeError("Paginazione bloccata: cursor non avanza")
                    if "search_id" in body and search_id != body["search_id"]:
                        raise RuntimeError("search_id cambiato durante la paginazione")
                    cursors.add(cursor)
                    body = {**body, "cursor": cursor, "search_id": search_id}
                    time.sleep(1)
        summary["status"] = "completed"
    except BudgetReached:
        summary["status"] = "partial_budget"
    except BaseException as exc:
        summary["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "error"
        summary["error_type"] = type(exc).__name__
        raise
    finally:
        summary["video_request_attempts"] = client.calls
        summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "riepilogo.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--start-date", help="Sostituisce start_date del file, formato YYYY-MM-DD")
    parser.add_argument("--end-date", help="Sostituisce end_date del file, formato YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Mostra richieste, senza rete e senza credenziali")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))
        for key in ("start_date", "end_date"):
            if getattr(args, key):
                config[key] = getattr(args, key)
        start, end = validate(config)
        if args.dry_run:
            for first, last in date_windows(start, end):
                print(json.dumps({"method": "POST", "url": VIDEO_URL,
                    "params": {"fields": ",".join(config["fields"])},
                    "body": make_body(config, first, last)}, ensure_ascii=False, indent=2))
            print("Anteprima: nessuna chiamata API. Sono mostrate solo le prime pagine di ogni finestra.")
            return 0
        from dotenv import load_dotenv
        load_dotenv(args.config.resolve().parent / ".env")
        key = os.getenv("TIKTOK_CLIENT_KEY") or os.getenv("C_KEY")
        secret = os.getenv("TIKTOK_CLIENT_SECRET") or os.getenv("C_SECRET")
        if not key or not secret:
            raise ValueError("Inserire TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET nel file .env accanto alla configurazione")
        base = args.config.resolve().parent / config.get("output_dir", "output")
        output = base / datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%S_%fZ")
        summary = collect(config, Client(key, secret, config["max_requests"]), output)
        print(f"Stato: {summary['status']}. Risultati: {output}")
        return 0 if summary["status"] == "completed" else 2
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, ImportError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrotto: le pagine già scritte sono conservate.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
