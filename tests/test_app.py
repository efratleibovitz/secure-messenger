"""
test_app.py — Stage 1 test suite.

╔══════════════════════════════════════════════════════════════════════╗
║  YOUR TASK: the test structure is given. Some tests are complete,   ║
║  others have a TODO for you to finish.                              ║
╚══════════════════════════════════════════════════════════════════════╝

HOW TO RUN:
  pytest tests/ -v

HOW TESTS WORK HERE:
  We use FastAPI's TestClient — it sends real HTTP requests to your app
  without needing to start a server. Each test gets a fresh, empty
  database so tests never interfere with each other.

  The test database is a separate file (test_messenger.db) and is
  wiped clean before every single test.
"""

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.main import app
from server.models import Base, get_db
from server.crypto import encrypt, decrypt


# ---------------------------------------------------------------------------
# Test database setup — uses a separate file, wiped before each test
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite:///./test_messenger.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def register_and_login(client, username="alice", password="secret123") -> str:
    """Register a user and return their JWT token."""
    client.post("/register", json={"username": username, "password": password})
    response = client.post("/login", json={"username": username, "password": password})
    return response.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# 1. Authentication tests
# ===========================================================================

class TestAuthentication:

    def test_register_success(self, client):
        response = client.post("/register", json={"username": "alice", "password": "secret123"})
        assert response.status_code == 201

    def test_register_duplicate_username(self, client):
        client.post("/register", json={"username": "alice", "password": "secret123"})
        response = client.post("/register", json={"username": "alice", "password": "other-password"})
        assert response.status_code == 400

    def test_register_password_too_short(self, client):
        response = client.post("/register", json={"username": "alice", "password": "abc"})
        assert response.status_code == 422   # Pydantic rejects it before your code runs

    def test_login_success(self, client):
        client.post("/register", json={"username": "alice", "password": "secret123"})
        response = client.post("/login", json={"username": "alice", "password": "secret123"})
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_login_wrong_password(self, client):
        client.post("/register", json={"username": "alice", "password": "secret123"})
        response = client.post("/login", json={"username": "alice", "password": "wrongpassword"})
        assert response.status_code == 401

    def test_login_unknown_user(self, client):
        response = client.post("/login", json={"username": "ghost", "password": "secret123"})
        assert response.status_code == 401

    def test_messages_require_token(self, client):
        response = client.get("/messages")
        assert response.status_code in (401, 403)

    def test_messages_reject_bad_token(self, client):
        response = client.get("/messages", headers={"Authorization": "Bearer fake-token"})
        assert response.status_code == 401

    def test_messages_accept_valid_token(self, client):
        token = register_and_login(client)
        response = client.get("/messages", headers=auth(token))
        assert response.status_code == 200


# ===========================================================================
# 2. Encryption tests
# ===========================================================================

class TestEncryption:

    def test_encrypt_is_not_plain_text(self):
        assert encrypt("hello world") != "hello world"

    def test_decrypt_round_trip(self):
        original = "this is a secret message"
        assert decrypt(encrypt(original)) == original

    def test_same_message_encrypts_differently_each_time(self):
        # fresh nonce every call → different ciphertext
        assert encrypt("hello") != encrypt("hello")

    def test_tampered_ciphertext_raises(self):
        blob = encrypt("original")
        tampered = blob[:-4] + "XXXX"
        with pytest.raises(Exception):
            decrypt(tampered)

    # TODO — complete this test:
    # After sending a message via POST /messages, query the database directly
    # and verify that the stored ciphertext is NOT the plain text,
    # but that decrypt(ciphertext) DOES return the original plain text.
    def test_messages_are_stored_encrypted(self, client):
        from server.models import Message
        token = register_and_login(client)
        # send a message
        # ... your code here ...
        # query the DB directly
        db = TestingSession()
        row = db.query(Message).first()
        db.close()
        # assert the ciphertext is not plain text
        # assert decrypt(ciphertext) returns the original
        pass


# ===========================================================================
# 3. Messaging tests
# ===========================================================================

class TestMessaging:

    def test_send_message_success(self, client):
        alice_token = register_and_login(client, "alice", "secret123")
        register_and_login(client, "bob", "secret456")

        response = client.post(
            "/messages",
            json={"content": "hello bob", "recipient": "bob"},
            headers=auth(alice_token),
        )
        assert response.status_code == 201
        data = response.json()
        assert data["content"] == "hello bob"   # returned decrypted
        assert data["sender"] == "alice"
        assert data["recipient"] == "bob"

    def test_get_messages_returns_decrypted(self, client):
        alice_token = register_and_login(client, "alice", "secret123")
        register_and_login(client, "bob", "secret456")

        client.post("/messages", json={"content": "hi bob", "recipient": "bob"}, headers=auth(alice_token))

        response = client.get("/messages", headers=auth(alice_token))
        assert response.status_code == 200
        messages = response.json()
        assert len(messages) >= 1
        assert messages[0]["content"] == "hi bob"   # must be decrypted, not ciphertext

    # TODO — complete this test:
    # Alice sends a message to Bob. Bob sends a message to Alice.
    # Verify that GET /messages returns ONLY the messages
    # where the requesting user is sender OR recipient.
    def test_user_sees_only_their_messages(self, client):
        alice_token = register_and_login(client, "alice", "secret123")
        bob_token   = register_and_login(client, "bob",   "secret456")
        charlie_token = register_and_login(client, "charlie", "secret789")

        # alice → bob
        client.post("/messages", json={"content": "hey bob", "recipient": "bob"}, headers=auth(alice_token))
        # charlie → bob  (alice should NOT see this)
        client.post("/messages", json={"content": "hey bob from charlie", "recipient": "bob"}, headers=auth(charlie_token))

        alice_messages = client.get("/messages", headers=auth(alice_token)).json()
        senders_recipients = [(m["sender"], m["recipient"]) for m in alice_messages]
        assert all("alice" in pair for pair in senders_recipients)
        assert not any(m["sender"] == "charlie" for m in alice_messages)


# ===========================================================================
# 4. SSE Stream tests
# ===========================================================================

class TestSSEStream:

    def test_stream_rejects_invalid_token(self, client):
        with client.stream("GET", "/stream", headers={"Authorization": "Bearer fake-token"}) as r:
            assert r.status_code == 401

    def test_stream_rejects_no_token(self, client):
        with client.stream("GET", "/stream") as r:
            assert r.status_code in (401, 403)

    def test_sse_stream_receives_broadcast(self, client):
        import asyncio
        from server.broadcaster import broadcaster

        alice_token = register_and_login(client, "alice", "secret123")
        bob_token   = register_and_login(client, "bob",   "secret456")

        # Directly test broadcaster: subscribe, publish, receive
        async def run():
            q = broadcaster.subscribe()
            await broadcaster.publish({"sender": "bob", "recipient": "alice", "content": "hello alice"})
            msg = await asyncio.wait_for(q.get(), timeout=2)
            broadcaster.unsubscribe(q)
            return msg

        msg = asyncio.run(run())
        assert msg["content"] == "hello alice"
        assert msg["sender"] == "bob"

        # Also verify the HTTP layer works
        r = client.post("/messages", json={"content": "hello alice", "recipient": "alice"}, headers=auth(bob_token))
        assert r.status_code == 201
        assert r.json()["content"] == "hello alice"

    def test_stream_only_delivers_relevant_messages(self, client):
        import asyncio
        from server.broadcaster import broadcaster

        register_and_login(client, "alice", "secret123")
        register_and_login(client, "charlie", "secret789")
        alice_token   = client.post("/login", json={"username": "alice",   "password": "secret123"}).json()["access_token"]
        charlie_token = client.post("/login", json={"username": "charlie", "password": "secret789"}).json()["access_token"]

        # Simulate broadcaster filtering: charlie should only get messages where he is sender/recipient
        async def run():
            q = broadcaster.subscribe()
            await broadcaster.publish({"sender": "alice", "recipient": "bob",     "content": "private to bob"})
            await broadcaster.publish({"sender": "alice", "recipient": "charlie", "content": "hello charlie"})
            messages = []
            for _ in range(2):
                msg = await asyncio.wait_for(q.get(), timeout=2)
                if msg["sender"] == "charlie" or msg["recipient"] == "charlie":
                    messages.append(msg)
            broadcaster.unsubscribe(q)
            return messages

        received = asyncio.run(run())
        assert len(received) == 1
        assert received[0]["content"] == "hello charlie"
        assert "private to bob" not in [m["content"] for m in received]
