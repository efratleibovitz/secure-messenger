"""
client.py — Terminal CLI for the Secure Messenger.

HOW TO RUN:
  uvicorn server.main:app --reload   (in one terminal)
  python -m client.client            (in another terminal)
"""

import json
import threading
import getpass
import httpx

BASE_URL = "http://localhost:8000"


def prompt_auth() -> tuple[str, str]:
    """Ask user to register or login. Returns (username, token)."""
    print("\n=== Secure Messenger ===")
    print("1) Register")
    print("2) Login")
    choice = input("Choose (1/2): ").strip()

    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")

    if choice == "1":
        r = httpx.post(f"{BASE_URL}/register", json={"username": username, "password": password})
        if r.status_code != 201:
            print(f"Registration failed: {r.json().get('detail')}")
            raise SystemExit(1)
        print("Registered successfully! Logging in...")

    r = httpx.post(f"{BASE_URL}/login", json={"username": username, "password": password})
    if r.status_code != 200:
        print(f"Login failed: {r.json().get('detail')}")
        raise SystemExit(1)

    token = r.json()["access_token"]
    return username, token


def show_history(token: str) -> None:
    """Print existing messages from GET /messages."""
    r = httpx.get(f"{BASE_URL}/messages", headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        return
    messages = r.json()
    if messages:
        print("\n--- Message history ---")
        for m in messages:
            print(f"  [{m['sender']} → {m['recipient']}]: {m['content']}")
        print("-----------------------")


def listen_for_messages(token: str) -> None:
    """Background thread: opens SSE stream and prints incoming messages."""
    try:
        with httpx.stream(
            "GET",
            f"{BASE_URL}/stream",
            headers={"Authorization": f"Bearer {token}"},
            timeout=None,
        ) as r:
            for line in r.iter_lines():
                if line.startswith("data:"):
                    raw = line[len("data:"):].strip()
                    try:
                        msg = json.loads(raw)
                        print(f"\n  [{msg['sender']} → {msg['recipient']}]: {msg['content']}")
                        print("  > ", end="", flush=True)
                    except Exception:
                        pass
    except Exception:
        print("\n[disconnected from server]")


def main():
    username, token = prompt_auth()
    show_history(token)

    print(f"\nWelcome, {username}!  (format: recipient:message  |  'quit' to exit)\n")

    t = threading.Thread(target=listen_for_messages, args=(token,), daemon=True)
    t.start()

    while True:
        try:
            line = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if line.lower() == "quit":
            break

        if ":" not in line:
            print("  Usage: recipient:message")
            continue

        recipient, _, content = line.partition(":")
        recipient = recipient.strip()
        content = content.strip()

        if not recipient or not content:
            print("  Usage: recipient:message")
            continue

        r = httpx.post(
            f"{BASE_URL}/messages",
            json={"recipient": recipient, "content": content},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code != 201:
            print(f"  Error: {r.json().get('detail')}")


if __name__ == "__main__":
    main()
