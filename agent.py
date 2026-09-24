from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()
API_BASE_URL = os.getenv("INVENTORY_API_URL", "http://127.0.0.1:8000")
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
LOG_FILE = os.getenv("CONVERSATION_LOG_FILE", "conversation_log.csv")
LOG_FIELDS = ["actor", "message", "tool_call", "timestamp"]

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_inventory",
            "description": "List every product and its current stock.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_product",
            "description": "Create a new inventory product.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 0},
                    "unit": {"type": "string"},
                },
                "required": ["name", "quantity", "unit"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adjust_stock",
            "description": "Apply a signed stock delta to a product id. Positive receives stock; negative sells stock.",
            "parameters": {
                "type": "object",
                "properties": {"product_id": {"type": "integer"}, "delta": {"type": "integer"}},
                "required": ["product_id", "delta"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inventory_alerts",
            "description": "Find products below a stock threshold (default 10).",
            "parameters": {
                "type": "object",
                "properties": {"threshold": {"type": "integer", "minimum": 0}},
                "additionalProperties": False,
            },
        },
    },
]


def log_event(actor: str, message: str, tool_call: str = "") -> None:
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=LOG_FIELDS)
        if not file_exists or os.path.getsize(LOG_FILE) == 0:
            writer.writeheader()
        writer.writerow(
            {
                "actor": actor,
                "message": message,
                "tool_call": tool_call,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


def execute_tool(name: str, arguments: dict[str, Any]) -> Any:
    with httpx.Client(base_url=API_BASE_URL, timeout=15) as client:
        if name == "list_inventory":
            response = client.get("/inventory")
        elif name == "create_product":
            response = client.post("/inventory", json=arguments)
        elif name == "adjust_stock":
            product_id = arguments["product_id"]
            response = client.patch(f"/inventory/{product_id}", json={"delta": arguments["delta"]})
        elif name == "inventory_alerts":
            response = client.get("/inventory/alerts", params=arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
        response.raise_for_status()
        return response.json()


def run_turn(client: OpenAI, history: list[dict[str, Any]], user_message: str) -> str:
    history.append({"role": "user", "content": user_message})
    log_event("user", user_message)
    while True:
        completion = client.chat.completions.create(model=MODEL, messages=history, tools=TOOLS)
        message = completion.choices[0].message
        assistant_message: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in message.tool_calls
            ]
        history.append(assistant_message)
        if not message.tool_calls:
            answer = message.content or "I could not produce a response."
            log_event("agent", answer)
            return answer
        for call in message.tool_calls:
            arguments = json.loads(call.function.arguments or "{}")
            tool_call = json.dumps({"name": call.function.name, "arguments": arguments})
            log_event("tool", "Calling inventory API", tool_call)
            try:
                result = execute_tool(call.function.name, arguments)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                result = {"error": str(exc)}
            serialized = json.dumps(result)
            log_event("tool", serialized, tool_call)
            history.append({"role": "tool", "tool_call_id": call.id, "content": serialized})


def main() -> None:
    if not os.getenv("GROQ_API_KEY"):
        raise SystemExit("GROQ_API_KEY is missing. Copy .env.example to .env and add your key.")
    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1")
    history: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": "You are a helpful inventory assistant. Use tools for all inventory facts and changes. Resolve product names with list_inventory before adjusting stock. Explain errors clearly.",
        }
    ]
    print("Inventory agent ready. Type 'exit' or 'quit' to stop.")
    while True:
        try:
            user_message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        if user_message.lower() in {"exit", "quit"}:
            print("Goodbye!")
            break
        if not user_message:
            continue
        try:
            print(f"Agent: {run_turn(client, history, user_message)}")
        except Exception as exc:
            print(f"Agent error: {exc}")


if __name__ == "__main__":
    main()
