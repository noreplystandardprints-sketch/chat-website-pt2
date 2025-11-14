# Chat App (Beta)

Single-file Flask + Socket.IO chat server with passcode-protected rooms, owner controls, file uploads, and local client-side memory for your username and room history.

This project is in beta. Expect breaking changes and incomplete security hardening. The repository is intended for code hosting on GitHub; deploy the server to your own host or platform.

Here is the link: https://chat-app-qryy.onrender.com/

## Overview

- One file: `app.py` embeds both the server and HTML templates.
- Host or join rooms using a room code and password.
- Remembers your username and recent rooms in `localStorage` for quick actions.
- Owner controls: lock/unlock room, mute/unmute, ban, clear chat, change password, close room.
- File uploads per-room, broadcast as links in chat.
- Real-time participants list with owner actions.

## Quick Start

1. Create a virtual environment and install dependencies:
   - `python3 -m venv venv`
   - `./venv/bin/pip install -r requirements.txt`
2. Run locally (change port if 5000 is busy):
   - `PORT=5001 ./venv/bin/python app.py`
3. Open in a browser:
   - `http://127.0.0.1:5001/`

## Configuration

- `CHAT_SECRET`: Flask secret key for sessions. Default is a dev key.
- `HOST`: Bind address (default `127.0.0.1`).
- `PORT`: Port (default `5000`).

Example:

- `CHAT_SECRET=your-secret HOST=0.0.0.0 PORT=8000 ./venv/bin/python app.py`

## Features

- Passcode-protected rooms: host a room with a code and password; join with the same.
- Room switching: switch to another room from the chat page using code/password; quick switch from recent rooms.
- Client memory: `localStorage` saves `chat_username`, `chat_rooms_hosted`, and `chat_rooms_joined`.
- Owner controls:
  - Lock/unlock: blocks new joins while locked.
  - Mute/unmute: prevents a user from sending messages.
  - Ban: disconnects and prevents rejoining by username.
  - Clear chat: clears the message view across clients.
  - Change password: updates the room password during session.
  - Close room: disconnects everyone and deletes the room.
- File uploads: stored under `uploads/<room>/`, shared as links in chat.

## Usage

- Portal (`/`):
  - Host a Room: set username, room code, and password.
  - Join a Room: enter a room code and password.
  - Recent rooms: quick actions to re-host or re-join rooms from your history.
- Chat Room (`/chat/<room>`):
  - Send messages, upload files, view participants.
  - Switch Rooms: enter target room code/password or use recent quick switches.
  - Owner Controls: manage participants and room state.

## Deployment (Production)

This is a server application; host it on a platform that supports long-lived connections (WebSocket) and Python.

- Gunicorn + Eventlet (recommended for Flask-SocketIO):
  - `./venv/bin/pip install gunicorn eventlet`
  - `gunicorn -k eventlet -w 1 -b 0.0.0.0:8000 app:app`
  - Place behind a reverse proxy (e.g., Nginx) with TLS.
- Alternatively use `gevent` workers.
- Ensure persistent storage for uploads or disable uploads in production.

Note: GitHub hosts the code; it does not run Flask apps. Use a server (VM, container, PaaS like Render/Railway/Fly.io) to run the app.

## Limitations (Beta)

- In-memory room registry: rooms, bans, and mutes reset on server restart.
- No account system: username is not authenticated; bans are per-username.
- Upload safety: basic filename handling only; no type whitelisting or virus scanning.
- Rate limiting, audit logging, and CSRF protections are minimal or absent.

## Roadmap

- Server-side accounts and persistent rooms (SQLite/PostgreSQL).
- Admin dashboard for room management.
- Upload type restrictions and scanning.
- Moderation tools and message history retention controls.

## Directory

- `app.py` — single-file server and templates.
- `requirements.txt` — dependencies.
- `uploads/` — per-room uploaded files.

## License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0
International License (CC BY-NC 4.0). See `LICENSE` for the full text.

In short: you may share and adapt the material for non-commercial purposes,
provided you give appropriate credit (attribution) to the author.
