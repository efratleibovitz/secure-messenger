"""
routes.py — All API route handlers.

╔══════════════════════════════════════════════╗
║  YOUR TASK: implement the four routes.       ║
╚══════════════════════════════════════════════╝

WHY A SEPARATE routes.py?
  In real projects, main.py only creates the app and wires things together.
  The actual logic lives in dedicated files — one per feature area.
  This keeps files small, focused, and easy to navigate.
  main.py imports this router and registers it with one line.

THE FOUR ROUTES YOU NEED TO IMPLEMENT:

  ┌─────────────────────────────────────────────────────────────────────┐
  │ POST /register                                                      │
  │   Receives: RegisterRequest (username, password)                    │
  │   1. Check if the username is already taken → return 400 if so     │
  │   2. Hash the password (NEVER store plain text)                     │
  │   3. Save the new User to the database                              │
  │   4. Return a success message                                       │
  └─────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────┐
  │ POST /login                                                         │
  │   Receives: LoginRequest (username, password)                       │
  │   1. Find the user in the database → return 401 if not found       │
  │   2. Verify the password against the stored hash → 401 if wrong    │
  │   3. Create and return a JWT token                                  │
  └─────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────┐
  │ POST /messages                          [requires valid JWT]        │
  │   Receives: SendMessageRequest (content, recipient)                 │
  │   1. Encrypt the content with encrypt()                             │
  │   2. Save a new Message row (sender=current user, recipient=...)    │
  │   3. Return the message as MessageResponse (with decrypted content) │
  └─────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────┐
  │ GET /messages                           [requires valid JWT]        │
  │   1. Fetch all messages from the database                           │
  │   2. Decrypt each message's ciphertext before returning             │
  │   3. Return a list of MessageResponse objects                       │
  │                                                                     │
  │   THINK ABOUT: should a user see ALL messages, or only those        │
  │   where they are the sender or recipient?                           │
  └─────────────────────────────────────────────────────────────────────┘

USEFUL IMPORTS ALREADY PROVIDED BELOW.
USEFUL PATTERN — how to query the database:
  user = db.query(User).filter(User.username == "alice").first()
  messages = db.query(Message).order_by(Message.created_at).all()

USEFUL PATTERN — how to save a new row:
  new_user = User(username="alice", password_hash="$2b$...")
  db.add(new_user)
  db.commit()
  db.refresh(new_user)   ← fills in the auto-generated id and created_at
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from .models import User, Message, get_db
from .schemas import (
    RegisterRequest, LoginRequest, TokenResponse,
    SendMessageRequest, MessageResponse,
)
from .auth import hash_password, verify_password, create_token, require_auth, require_auth_flexible
from .crypto import encrypt, decrypt
from .broadcaster import broadcaster


log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# TODO 1 — Register a new user
# ---------------------------------------------------------------------------
@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    # Check if username already exists
    existing_user = db.query(User).filter(User.username == body.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="username already taken"
        )
    
    # Hash the password
    hashed_pw = hash_password(body.password)
    
    # Create and save the new user
    new_user = User(username=body.username, password_hash=hashed_pw)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    log.info(f"User registered: {body.username}")
    return {"message": f"User {body.username} registered successfully", "user_id": new_user.id}


# ---------------------------------------------------------------------------
# TODO 2 — Login and receive a JWT token
# ---------------------------------------------------------------------------
@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    # Find the user in the database
    user = db.query(User).filter(User.username == body.username).first()
    if not user:
        # Hash anyway to prevent timing-based username enumeration
        hash_password(body.password)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    # Verify the password against the stored hash
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    # Create and return a JWT token
    token = create_token(body.username)
    log.info(f"User logged in: {body.username}")
    return TokenResponse(access_token=token)


# ---------------------------------------------------------------------------
# TODO 3 — Send a message (authenticated)
# ---------------------------------------------------------------------------
@router.post("/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    body: SendMessageRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_auth),
):
    ciphertext = encrypt(body.content)
    new_message = Message(
        sender=username,
        recipient=body.recipient,
        ciphertext=ciphertext
    )
    db.add(new_message)
    db.commit()
    db.refresh(new_message)

    response = MessageResponse(
        id=new_message.id,
        sender=username,
        recipient=body.recipient,
        content=body.content,
        created_at=new_message.created_at
    )
    await broadcaster.publish(response.model_dump(mode="json"))
    log.info(f"Message sent from {username} to {body.recipient}")
    return response


# ---------------------------------------------------------------------------
# Stream — SSE real-time endpoint
# ---------------------------------------------------------------------------
@router.get("/stream")
async def stream(
    db: Session = Depends(get_db),
    username: str = Depends(require_auth_flexible),
) -> EventSourceResponse:
    q = broadcaster.subscribe()

    async def event_generator():
        try:
            while True:
                message = await q.get()
                if message["sender"] == username or message["recipient"] == username:
                    yield {"event": "message", "data": json.dumps(message)}
        except asyncio.CancelledError:
            raise
        finally:
            broadcaster.unsubscribe(q)

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# TODO 4 — Fetch messages (authenticated)
# ---------------------------------------------------------------------------
@router.get("/messages", response_model=list[MessageResponse])
def get_messages(
    db: Session = Depends(get_db),
    username: str = Depends(require_auth),
):
    # Fetch messages where the user is the sender OR recipient
    messages = db.query(Message).filter(
        (Message.sender == username) | (Message.recipient == username)
    ).order_by(Message.created_at).all()
    
    # Decrypt each message and return as MessageResponse
    result = []
    for msg in messages:
        decrypted_content = decrypt(msg.ciphertext)
        result.append(MessageResponse(
            id=msg.id,
            sender=msg.sender,
            recipient=msg.recipient,
            content=decrypted_content,  # Decrypted plain text
            created_at=msg.created_at
        ))
    
    log.info(f"User {username} fetched {len(result)} messages")
    return result
