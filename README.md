# AI Basic Inventory Agent Loop

A two-component Python project: a FastAPI inventory service backed by CSV files and a plain-Python AI assistant that manually runs an LLM tool-calling loop against that API. It uses the OpenAI SDK with Groq's OpenAI-compatible endpoint and does not use an agent framework.

## Architecture

- `api/app.py`: FastAPI inventory endpoints.
- `products.csv`: durable inventory state, created automatically.
- `agent.py`: terminal chat client with in-memory conversation history, typed tool schemas, and the loop Observe → Think → Act → Update → Repeat.
- `conversation_log.csv`: append-only audit log for user, tool, and agent events.

## Environment

Copy `.env.example` to `.env` and set:

```dotenv
GROQ_API_KEY=your_key_here
GROQ_MODEL=llama-3.3-70b-versatile
INVENTORY_API_URL=http://127.0.0.1:8000
```

`.env` is ignored by Git. Never commit API keys.

## Installation

Use Python 3.10+ and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

Start the API in **Terminal 1**:

```bash
uvicorn api.app:app --reload
```

Start the agent in **Terminal 2**:

```bash
python agent.py
```

Type `exit` or `quit` for a clean shutdown. The agent keeps the complete conversation history for the current execution and supports multi-step calls, such as listing inventory to resolve a product name before applying a stock adjustment.

## Example conversations

- `we just received 30 units of oat milk` — finds oat milk and applies `+30`.
- `we sold 12 bags of arabica today` — finds arabica and applies `-12`.
- `what products are running low?` — calls the alerts endpoint and summarizes the result.
- `add 25 bottles of sparkling water` — creates a product when appropriate.

## API endpoints

- `GET /inventory`: list all products.
- `POST /inventory`: create `{ "name": "oat milk", "quantity": 12, "unit": "units" }`.
- `PATCH /inventory/{product_id}`: update with `{ "delta": 30 }` or `{ "delta": -12 }`.
- `GET /inventory/alerts?threshold=10`: products strictly below the threshold.

The API validates quantities, rejects negative resulting stock, returns 404 for unknown IDs, and atomically replaces the CSV after successful writes. `products.csv` survives API restarts and failed requests do not silently corrupt it.

## Conversation log

`conversation_log.csv` is opened in append mode for every event and is never overwritten between executions. Every row has exactly `actor,message,tool_call,timestamp`; timestamps are ISO 8601. It records user prompts, tool calls, tool results, and final agent responses.
