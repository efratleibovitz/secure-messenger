"""
seed.py — Populate the database with test data.

HOW TO RUN:
  python seed.py
"""

from server.models import engine, SessionLocal, Base, User, Message
from server.auth import hash_password
from server.crypto import encrypt


def seed():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    users = [
        User(username="alice", password_hash=hash_password("secret123")),
        User(username="bob",   password_hash=hash_password("secret456")),
        User(username="charlie", password_hash=hash_password("secret789")),
    ]
    db.add_all(users)
    db.commit()

    messages = [
        Message(sender="alice",   recipient="bob",     ciphertext=encrypt("hey bob!")),
        Message(sender="bob",     recipient="alice",   ciphertext=encrypt("hi alice, what's up?")),
        Message(sender="alice",   recipient="bob",     ciphertext=encrypt("let's sync later")),
        Message(sender="charlie", recipient="alice",   ciphertext=encrypt("alice, are you free?")),
        Message(sender="bob",     recipient="charlie", ciphertext=encrypt("charlie, join us!")),
    ]
    db.add_all(messages)
    db.commit()
    db.close()

    print("Database seeded: 3 users, 5 messages.")


if __name__ == "__main__":
    seed()
