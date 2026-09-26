# Aurora Support — AI store assistant

Aurora is a **RAG** support & sales assistant for a small online electronics
store. It answers policy and how-to questions by **retrieving** relevant articles
from a knowledge base (`knowledge_base/`, embedded with sentence-transformers),
and looks up **live data** from the store database — products, orders, accounts,
support tickets — using tool calls. The model runs on your local Hermes/Claude,
so no API key is needed. Front-end runs in your browser.

## Setup

```bash
pip install -r requirements.txt
```

Set your Claude key in `.env` (or leave it blank to reuse the key from your local
Hermes install):

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Run

```bash
python store_db.py     # build the demo database (once)
python rag.py          # build the knowledge-base index (once; first run downloads the embed model ~90MB)
python server.py       # start the web app
```

Open **http://127.0.0.1:5000**. You're signed in as a sample customer. Try:

```
show me laptops under 1200
what's the status of my orders?
I got the wrong item — can you file a ticket?
```

## How it works

- `server.py` runs the agent loop: Claude picks tools, the server runs them
  against `store.db`, and the results go back to Claude to form the answer.
- `store_db.py` builds the SQLite database with sample products, customers,
  orders, tickets, and store settings.
- `web/index.html` is the chat UI; it shows each database lookup Aurora makes.

## Tools

| Tool              | What it does                          |
|-------------------|---------------------------------------|
| `search_products` | Search the catalog                    |
| `get_customer`    | Look up an account by email           |
| `get_orders`      | List a customer's orders              |
| `list_tickets`    | Read open support tickets             |
| `create_ticket`   | File a new support ticket             |

MIT licensed.
