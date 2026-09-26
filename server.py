#!/usr/bin/env python3
"""
Aurora — support assistant web backend.

A small HTTP server hosting Aurora, the AI support agent for the (fictional)
Aurora Electronics store. The browser front-end (web/index.html) talks to it
over a tiny JSON API; Aurora reasons with an LLM and answers by querying the
store database (store.db) through its tools.

Runs on Claude if an Anthropic key is available, otherwise on an OpenAI model.

    python store_db.py     # once, to build the database
    python server.py       # then open http://127.0.0.1:5000
"""

import os
import json
import sqlite3
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

try:
    import rag
except Exception:
    rag = None

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

def load_env(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_env()


def _from_hermes_env(name):
    """Borrow a key already configured for the local Hermes install."""
    hermes_env = os.path.expanduser("~/AppData/Local/hermes/.env")
    if not os.path.exists(hermes_env):
        return ""
    with open(hermes_env, "r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith(name + "="):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _find_hermes():
    import shutil
    env_bin = os.environ.get("HERMES_BIN", "").strip()
    if env_bin and os.path.exists(env_bin):
        return env_bin
    found = shutil.which("hermes")
    if found:
        return found
    guess = os.path.expanduser("~/AppData/Local/hermes/hermes-agent/bin/hermes.exe")
    return guess if os.path.exists(guess) else ""


ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip() or _from_hermes_env("ANTHROPIC_API_KEY")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1"
HERMES_BIN = _find_hermes()

PROVIDER = os.environ.get("PROVIDER", "").strip().lower()
if not PROVIDER:
    if ANTHROPIC_KEY:
        PROVIDER = "anthropic"
    elif OPENAI_KEY:
        PROVIDER = "openai"
    elif HERMES_BIN:
        PROVIDER = "hermes"
    else:
        PROVIDER = ""

MODEL = os.environ.get("MODEL", "").strip()
if not MODEL:
    MODEL = {"anthropic": "claude-opus-4-8", "openai": "gpt-4o-mini"}.get(PROVIDER, "hermes")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5000"))
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "store.db")

# The customer this browser session is signed in as.
SESSION_EMAIL = "kavi@gmail.com"


# ----------------------------------------------------------------------------
# Aurora's instructions
# ----------------------------------------------------------------------------

SYSTEM_PROMPT = f"""You are Aurora, the AI Shopping & Support Assistant for Aurora
Electronics, an online electronics store in India. You help customers discover
products, check prices and stock, track their orders, and manage their account.

The customer signed in to this chat is {SESSION_EMAIL}.

Guidelines:
- Introduce yourself as Aurora, Aurora Electronics' shopping and support
  assistant, if the customer greets you or asks who you are.
- Be warm, concise, and genuinely helpful. Use your tools to look up real data
  before answering — never make up prices, stock, or order details.
- All prices and totals are in Indian Rupees. Always show money with the ₹ symbol
  and Indian-style grouping (e.g. ₹89,999), never dollars.
- Account and order details are private: only share them for the signed-in
  customer. If someone asks about a different account, verify their identity
  before helping.
- Keep the conversation professional and on-brand for Aurora Electronics.

For policy, returns, warranty, shipping, payment, and general how-to questions,
use search_knowledge_base and answer from the retrieved help-center articles,
mentioning which article you used. Use the product and order tools for live
product, price, stock, and order data. Use the account and ticket tools for
account questions.
"""


# ----------------------------------------------------------------------------
# Input validation (a light safety filter)
# ----------------------------------------------------------------------------

WAF_BLOCK = [
    "union", "select", "insert", "update", "delete", "drop",
    " or ", "1=1", "information_schema", "/*",
]


def waf(value: str):
    for bad in WAF_BLOCK:
        if bad in value:
            return bad
    return None


# ----------------------------------------------------------------------------
# Database tools
# ----------------------------------------------------------------------------

def _query(sql: str):
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, cur.fetchall()
    finally:
        con.close()


def _format(cols, rows):
    if not rows:
        return "(no rows)"
    lines = [" | ".join(cols)]
    for r in rows:
        lines.append(" | ".join("" if v is None else str(v) for v in r))
    return "\n".join(lines)


def search_products(query: str) -> str:
    bad = waf(query)
    if bad:
        return f"[blocked: search rejected by input validation (matched '{bad.strip()}')]"
    sql = f"SELECT id, name, category, price, stock FROM products WHERE name LIKE '%{query}%'"
    try:
        return _format(*_query(sql))
    except Exception as exc:
        return f"[query error: {exc}]"


def _search_rows(query: str):
    """Structured product search used by the website's search box (GET /api/search)."""
    bad = waf(query)
    if bad:
        return {"error": f"Search rejected by input validation (matched '{bad.strip()}')."}
    sql = f"SELECT id, name, category, price, stock FROM products WHERE name LIKE '%{query}%'"
    try:
        cols, rows = _query(sql)
        return {"columns": cols, "rows": [list(r) for r in rows]}
    except Exception as exc:
        return {"error": str(exc)}


def get_customer(email: str) -> str:
    bad = waf(email)
    if bad:
        return f"[blocked: rejected by input validation (matched '{bad.strip()}')]"
    sql = f"SELECT name, email, phone, address FROM customers WHERE email = '{email}'"
    try:
        return _format(*_query(sql))
    except Exception as exc:
        return f"[query error: {exc}]"


def get_orders(email: str) -> str:
    bad = waf(email)
    if bad:
        return f"[blocked: rejected by input validation (matched '{bad.strip()}')]"
    sql = (
        "SELECT o.id, o.status, o.total, o.created_at, p.name AS product "
        "FROM orders o JOIN customers c ON o.customer_id = c.id "
        "JOIN products p ON o.product_id = p.id "
        f"WHERE c.email = '{email}'"
    )
    try:
        return _format(*_query(sql))
    except Exception as exc:
        return f"[query error: {exc}]"


def get_order(order_id: str) -> str:
    bad = waf(str(order_id))
    if bad:
        return f"[blocked: rejected by input validation (matched '{bad.strip()}')]"
    sql = (
        "SELECT o.id, o.status, o.total, o.created_at, p.name AS product, "
        "c.name AS customer, c.address AS delivery_address "
        "FROM orders o JOIN products p ON o.product_id = p.id "
        "JOIN customers c ON o.customer_id = c.id "
        f"WHERE o.id = {order_id}"
    )
    try:
        return _format(*_query(sql))
    except Exception as exc:
        return f"[query error: {exc}]"


def list_tickets() -> str:
    try:
        return _format(*_query(
            "SELECT id, subject, message, status FROM support_tickets WHERE status = 'open'"))
    except Exception as exc:
        return f"[query error: {exc}]"


def create_ticket(email: str, subject: str, message: str) -> str:
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            "INSERT INTO support_tickets (customer_id, subject, message, status) "
            "SELECT id, ?, ?, 'open' FROM customers WHERE email = ?",
            (subject, message, email),
        )
        con.commit()
        con.close()
        return "ticket created"
    except Exception as exc:
        return f"[error: {exc}]"


def search_knowledge_base(query: str) -> str:
    if rag is None:
        return "[knowledge base unavailable]"
    try:
        hits = rag.retrieve(query, k=2)
    except Exception as exc:
        return f"[kb error: {exc}]"
    if not hits:
        return "(no articles found)"
    return "\n\n---\n\n".join(f"[source: {h['source']}]\n{h['text']}" for h in hits)


TOOLS = {
    "search_products": lambda **k: search_products(k.get("query", "")),
    "search_knowledge_base": lambda **k: search_knowledge_base(k.get("query", "")),
    "get_customer": lambda **k: get_customer(k.get("email", "")),
    "get_orders": lambda **k: get_orders(k.get("email", "")),
    "get_order": lambda **k: get_order(k.get("order_id", "")),
    "list_tickets": lambda **k: list_tickets(),
    "create_ticket": lambda **k: create_ticket(k.get("email", ""), k.get("subject", ""), k.get("message", "")),
}

# Shared tool schema (JSON Schema for each tool's arguments).
TOOL_DEFS = [
    ("search_products", "Search the product catalog by name or keyword.",
     {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
    ("search_knowledge_base", "Search the Aurora help center (FAQs, returns, warranty, shipping, payment, buying guide) for policy and how-to answers.",
     {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
    ("get_customer", "Look up a customer account by email address.",
     {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]}),
    ("get_orders", "List the orders for a customer, by their email address.",
     {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]}),
    ("get_order", "Look up a single order by its order number (id), with status and delivery details.",
     {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}),
    ("list_tickets", "List all open support tickets.",
     {"type": "object", "properties": {}}),
    ("create_ticket", "File a new support ticket for a customer.",
     {"type": "object", "properties": {
         "email": {"type": "string"}, "subject": {"type": "string"}, "message": {"type": "string"}},
         "required": ["email", "subject", "message"]}),
]

ANTHROPIC_TOOLS = [{"name": n, "description": d, "input_schema": s} for n, d, s in TOOL_DEFS]
OPENAI_TOOLS = [{"type": "function", "function": {"name": n, "description": d, "parameters": s}}
                for n, d, s in TOOL_DEFS]


def run_tool(name, args):
    fn = TOOLS.get(name)
    result = fn(**(args or {})) if fn else f"[unknown tool: {name}]"
    event = {
        "type": "tool", "name": name, "args": args or {},
        "result": (result[:800] + "…") if len(result) > 800 else result,
        "blocked": result.startswith("[blocked"),
    }
    return result, event


# ----------------------------------------------------------------------------
# Provider-specific agent loops
# ----------------------------------------------------------------------------

_client = None


def get_client():
    global _client
    if _client is not None:
        return _client
    if PROVIDER == "anthropic":
        import anthropic
        _client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    else:
        from openai import OpenAI
        _client = OpenAI(api_key=OPENAI_KEY, base_url=OPENAI_BASE_URL)
    return _client


# Conversation is provider-native. For OpenAI it starts with the system message.
conversation = [] if PROVIDER == "anthropic" else [{"role": "system", "content": SYSTEM_PROMPT}]


def run_turn_anthropic(user_text):
    events = []
    client = get_client()
    conversation.append({"role": "user", "content": user_text})
    for _ in range(12):
        resp = client.messages.create(
            model=MODEL, max_tokens=1200, system=SYSTEM_PROMPT,
            messages=conversation, tools=ANTHROPIC_TOOLS)
        assistant, tool_uses = [], []
        for block in resp.content:
            if block.type == "text":
                assistant.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
                tool_uses.append(block)
        conversation.append({"role": "assistant", "content": assistant})
        if resp.stop_reason != "tool_use":
            return ("".join(b["text"] for b in assistant if b["type"] == "text") or "(no reply)", events)
        results = []
        for tu in tool_uses:
            result, event = run_tool(tu.name, tu.input)
            events.append(event)
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": str(result)})
        conversation.append({"role": "user", "content": results})
    return ("(stopped after too many steps)", events)


def run_turn_openai(user_text):
    events = []
    client = get_client()
    conversation.append({"role": "user", "content": user_text})
    for _ in range(12):
        resp = client.chat.completions.create(
            model=MODEL, messages=conversation, tools=OPENAI_TOOLS, temperature=0.3)
        msg = resp.choices[0].message
        conversation.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            return (msg.content or "(no reply)", events)
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result, event = run_tool(call.function.name, args)
            events.append(event)
            conversation.append({"role": "tool", "tool_call_id": call.id, "content": str(result)})
    return ("(stopped after too many steps)", events)


# --- Hermes CLI backend (no API key needed; Hermes handles Claude auth) ---

hermes_history = []  # list of transcript strings

_TOOL_CATALOG = "\n".join(f"- {n}(args: {list(s.get('properties', {}).keys())}): {d}"
                          for n, d, s in TOOL_DEFS)

HERMES_FRAMING = f"""{SYSTEM_PROMPT}

To look things up you can use these helper functions:
{_TOOL_CATALOG}

You answer one step at a time using a small JSON format:
- When you need data, reply with:  {{"tool": "<name>", "args": {{ ... }}}}
- When you're ready to talk to the customer, reply with:  {{"reply": "<your friendly message>"}}

For the current step, give just that one JSON object so the app can process it.
"""


def _extract_json(text):
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        start = None
    return None


_HERMES_FAIL = ("try rephrasing", "the model declined", "model returned no",
                "fallback provider", "hermes fallback add")


def _hermes_call(prompt, tries=5):
    import subprocess, time
    raw = ""
    for _ in range(tries):
        try:
            proc = subprocess.run(
                [HERMES_BIN, "chat", "--query-file", "-", "-Q", "-t", "",
                 "--reasoning", "none", "--ignore-rules", "--ignore-user-config"],
                input=prompt, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=180,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            raw = proc.stdout or ""
        except Exception:
            raw = ""
        low = raw.lower()
        if raw.strip() and not any(f in low for f in _HERMES_FAIL):
            return raw
        time.sleep(0.3)  # transient hiccup / refusal banner -> retry
    return raw


def _clean_hermes(raw):
    out = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s:
            continue
        low = s.lower()
        if s.startswith("session_id:") or s.startswith("Warning:") or "⚠" in s:
            continue
        if any(f in low for f in _HERMES_FAIL):
            continue
        if "deprecated" in low or "move to config" in low or "then remove" in low:
            continue
        out.append(s)
    return "\n".join(out).strip()


def run_turn_hermes(user_text):
    events = []
    hermes_history.append(f"User: {user_text}")
    for _ in range(8):
        prompt = (HERMES_FRAMING + "\n\nConversation so far:\n"
                  + "\n".join(hermes_history)
                  + "\n\nRespond with the next single JSON object:")
        raw = _hermes_call(prompt)
        obj = _extract_json(raw)
        if not obj:
            cleaned = _clean_hermes(raw)
            reply = cleaned or "Sorry, I'm having a little trouble right now — could you try that again?"
            hermes_history.append(f"Assistant: {reply}")
            return (reply, events)
        if "tool" in obj:
            name = obj.get("tool")
            args = obj.get("args", {}) or {}
            result, event = run_tool(name, args)
            events.append(event)
            hermes_history.append(f'Assistant: {json.dumps(obj)}')
            hermes_history.append(f"Tool({name}): {result}")
            continue
        reply = obj.get("reply", "(no reply)")
        hermes_history.append(f'Assistant: {json.dumps(obj)}')
        return (reply, events)
    return ("(stopped after too many steps)", events)


def run_turn(user_text):
    if PROVIDER == "anthropic":
        return run_turn_anthropic(user_text)
    if PROVIDER == "hermes":
        return run_turn_hermes(user_text)
    return run_turn_openai(user_text)


# ----------------------------------------------------------------------------
# HTTP server
# ----------------------------------------------------------------------------

def load_page():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                self._send(200, load_page(), "text/html; charset=utf-8")
            except Exception as exc:
                self._send(500, f"cannot load UI: {exc}", "text/plain")
        elif self.path == "/api/session":
            self._send(200, json.dumps({"email": SESSION_EMAIL, "model": MODEL, "provider": PROVIDER}))
        elif self.path == "/api/products":
            try:
                con = sqlite3.connect(DB_PATH)
                rows = con.execute(
                    "SELECT id, name, category, price, stock, description "
                    "FROM products ORDER BY category, price DESC").fetchall()
                con.close()
                items = [{"id": r[0], "name": r[1], "category": r[2],
                          "price": r[3], "stock": r[4], "description": r[5]} for r in rows]
                self._send(200, json.dumps({"products": items}))
            except Exception as exc:
                self._send(500, json.dumps({"error": str(exc)}))
        elif self.path.startswith("/api/search"):
            from urllib.parse import urlparse, parse_qs, unquote_plus
            qs = parse_qs(urlparse(self.path).query)
            query = unquote_plus(qs.get("q", [""])[0])
            self._send(200, json.dumps(_search_rows(query)))
        elif self.path.startswith("/images/"):
            from urllib.parse import urlparse, unquote
            name = os.path.basename(unquote(urlparse(self.path).path))
            fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "images", name)
            if os.path.isfile(fpath):
                with open(fpath, "rb") as fh:
                    data = fh.read()
                ct = "image/jpeg" if name.lower().endswith((".jpg", ".jpeg")) else \
                     "image/png" if name.lower().endswith(".png") else \
                     "image/webp" if name.lower().endswith(".webp") else "application/octet-stream"
                self._send(200, data, ct)
            else:
                self._send(404, "not found", "text/plain")
        elif self.path.startswith("/api/kb_search"):
            from urllib.parse import urlparse, parse_qs, unquote_plus
            qs = parse_qs(urlparse(self.path).query)
            query = unquote_plus(qs.get("q", [""])[0])
            try:
                hits = rag.retrieve(query, k=4) if rag else []
            except Exception:
                hits = []
            self._send(200, json.dumps({"results": hits}))
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            payload = {}

        if self.path == "/api/reset":
            conversation.clear()
            hermes_history.clear()
            if PROVIDER == "openai":
                conversation.append({"role": "system", "content": SYSTEM_PROMPT})
            self._send(200, json.dumps({"ok": True}))
            return

        if self.path == "/api/chat":
            message = (payload.get("message") or "").strip()
            if not message:
                self._send(400, json.dumps({"error": "empty message"}))
                return
            try:
                reply, events = run_turn(message)
            except Exception as exc:
                self._send(200, json.dumps({"reply": f"[error: {exc}]", "events": []}))
                return
            self._send(200, json.dumps({"reply": reply, "events": events}))
            return

        self._send(404, json.dumps({"error": "not found"}))


def main():
    if not os.path.exists(DB_PATH):
        print("store.db not found — run `python store_db.py` first.")
        return
    if not PROVIDER:
        print("No API key found. Set ANTHROPIC_API_KEY (or OPENAI_API_KEY) in .env.")
        return
    if rag is not None:
        try:
            print("  building knowledge-base index…")
            rag.build_index()
            print(f"  knowledge base: {len(rag._chunks)} chunks ready")
        except Exception as exc:
            print(f"  knowledge base unavailable: {exc}")
    print(f"  Aurora support  ·  provider: {PROVIDER}  ·  model: {MODEL}")
    print(f"  signed in as:  {SESSION_EMAIL}")
    print(f"  open:          http://{HOST}:{PORT}\n")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
