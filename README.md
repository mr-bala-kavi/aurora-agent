# Aurora — RAG AI Support Agent (AI Security Demo)

A **RAG-based AI support agent** for a demo online electronics store — built to
teach **AI security and web application security** in a safe, hands-on way. It
shows how a modern AI agent is put together, how it can be **attacked**
(SQL injection, broken access control / IDOR, RAG knowledge-base leaks, hidden
endpoints), and **how to secure it**.

> ⚠️ This project is intentionally insecure, for learning only. Run it on your
> own machine and never point these techniques at systems you don't own.

## What's inside

- **RAG agent** — retrieves answers from a markdown knowledge base
  (`knowledge_base/`, embedded with sentence-transformers) and queries a SQLite
  store through tools.
- **Backend** — a small Python server running the agent loop on **Claude**
  (via a local Hermes install, so no API key is needed).
- **Front-end** — a storefront web page with a support chat widget.
- **Security lab** — `attack/hack-payloads.txt` has copy-paste commands for every
  demo.

## Setup

```bash
pip install -r requirements.txt
```

The model runs on your local Hermes/Claude, so no API key is required. To use an
API key instead, set `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) in a `.env` file.

## Run

```bash
python store_db.py     # build the demo database (once)
python rag.py          # build the knowledge-base index (once; first run downloads the embed model ~90MB)
python server.py       # start the web app
```

Open **http://127.0.0.1:5000**. You're signed in as a sample customer. Try:

```
show me laptops
what's your return policy for laptops?
track my orders
```

## How it works

- `server.py` runs the agent loop: Claude picks a tool, the server runs it
  against `store.db` (or the RAG index), and the result goes back to Claude to
  form the answer.
- `rag.py` embeds and retrieves the knowledge-base articles.
- `store_db.py` builds the SQLite database with sample products, customers,
  orders, tickets, and settings.
- `web/index.html` is the storefront + chat widget.

## Security testing (educational)

All demo payloads and commands are in **`attack/hack-payloads.txt`** — database
fingerprinting, SQL injection, schema discovery, the RAG retrieval leak, and
hidden-endpoint discovery — with notes on **why** each works and **how to fix**
it. For authorized, educational use only.

---

🎓 **TO JOIN OUR COURSE:** https://kavisnetwork.in/saaspt/

## 🔐 Cyber Security × AI Security — in Tamil

Learn Cyber Security and AI Security in Tamil — ethical hacking, penetration
testing, AI security, automation, and real hands-on demos to help you build
practical skills and grow your career.

> ⚠️ **Disclaimer:** This content is for educational purposes only. All
> demonstrations are conducted in controlled/lab environments. Do not attempt any
> techniques shown here on systems you don't own or have explicit permission to
> test. Unauthorized access or attacks are illegal. Use this knowledge
> responsibly and ethically.

🔔 Subscribe for weekly videos on Cybersecurity, AI Security, Python automation,
and career guidance.

## 🔗 Connect with me

- 🌐 Website: https://kavisnetwork.in/
- 🎯 Mentorship (1:1 Career Guidance): https://topmate.io/kavis_network/
- 💻 GitHub (Tools & Scripts): https://github.com/mr-bala-kavi
- 💼 LinkedIn: https://www.linkedin.com/in/balakavi/
- 📸 Instagram: https://www.instagram.com/kavi.s_network
- 🎥 YouTube: https://www.youtube.com/@KavisNetwork

For corporate cybersecurity training or AI security consulting inquiries, reach
out via the links above.
