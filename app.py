import os
from flask import Flask, request, redirect, url_for, session, send_from_directory, flash
from flask import render_template_string
from flask_socketio import SocketIO, join_room, emit, disconnect


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('CHAT_SECRET', 'dev-secret-key')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20 MB per upload

socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory room registry: {
#   room: {
#     password: str,
#     owner_sid: str|None,
#     locked: bool,
#     banned: set[str],
#     muted: set[str],
#     participants: { sid: { username: str, is_owner: bool } }
#   }
# }
ROOMS: dict[str, dict] = {}


INDEX_HTML = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Chat Portal</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/sakura.css/css/sakura.css">
  </head>
  <body>
    <h1>Chat Portal</h1>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <ul>
          {% for message in messages %}
            <li>{{ message }}</li>
          {% endfor %}
        </ul>
      {% endif %}
    {% endwith %}
    <div style="display:flex; gap:2rem; flex-wrap:wrap;">
      <section>
        <h3>Host a Room</h3>
        <form id="host-form" method="post" action="{{ url_for('host') }}">
          <label>Username</label>
          <input id="host-username" type="text" name="username" placeholder="Your name" required>
          <label>Room Code</label>
          <input type="text" name="room" placeholder="room-123" required>
          <label>Password</label>
          <input type="text" name="password" placeholder="Set a password" required>
          <button type="submit">Host</button>
        </form>
        <div>
          <h4>Recently Hosted</h4>
          <div id="recent-hosted"></div>
        </div>
      </section>
      <section>
        <h3>Join a Room</h3>
        <form id="join-form" method="post" action="{{ url_for('join') }}">
          <label>Username</label>
          <input id="join-username" type="text" name="username" placeholder="Your name" required>
          <label>Room Code</label>
          <input type="text" name="room" placeholder="room-123" required>
          <label>Password</label>
          <input type="text" name="password" placeholder="Room password" required>
          <button type="submit">Join</button>
        </form>
        <div>
          <h4>Recently Joined</h4>
          <div id="recent-joined"></div>
        </div>
      </section>
    </div>
    <script>
      function getJSON(key, fallback) {
        try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (_) { return fallback; }
      }
      function setJSON(key, value) { localStorage.setItem(key, JSON.stringify(value)); }

      // Prefill usernames
      const savedName = localStorage.getItem('chat_username') || '';
      document.getElementById('host-username').value = savedName;
      document.getElementById('join-username').value = savedName;

      // Render recent rooms
      const hosted = getJSON('chat_rooms_hosted', []);
      const joined = getJSON('chat_rooms_joined', []);
      function renderList(el, rooms, mode) {
        el.innerHTML = '';
        if (!rooms.length) { el.textContent = 'None'; return; }
        rooms.slice(-10).reverse().forEach(r => {
          const div = document.createElement('div');
          const span = document.createElement('span');
          span.textContent = r.room + ' (last: ' + new Date(r.ts).toLocaleString() + ')';
          div.appendChild(span);
          const btn = document.createElement('button');
          btn.textContent = mode === 'host' ? 'Host' : 'Join';
          btn.onclick = () => {
            const form = document.getElementById(mode === 'host' ? 'host-form' : 'join-form');
            form.querySelector('input[name="room"]').value = r.room;
            form.querySelector('input[name="password"]').value = r.password || '';
            form.submit();
          };
          div.appendChild(btn);
          el.appendChild(div);
        });
      }
      renderList(document.getElementById('recent-hosted'), hosted, 'host');
      renderList(document.getElementById('recent-joined'), joined, 'join');

      // Save username and room history on submit
      document.getElementById('host-form').addEventListener('submit', (e) => {
        const name = document.getElementById('host-username').value.trim();
        if (name) localStorage.setItem('chat_username', name);
        const room = e.target.querySelector('input[name="room"]').value.trim();
        const pw = e.target.querySelector('input[name="password"]').value.trim();
        if (room) {
          const list = getJSON('chat_rooms_hosted', []);
          list.push({ room, password: pw, ts: Date.now() });
          setJSON('chat_rooms_hosted', list);
        }
      });
      document.getElementById('join-form').addEventListener('submit', (e) => {
        const name = document.getElementById('join-username').value.trim();
        if (name) localStorage.setItem('chat_username', name);
        const room = e.target.querySelector('input[name="room"]').value.trim();
        const pw = e.target.querySelector('input[name="password"]').value.trim();
        if (room) {
          const list = getJSON('chat_rooms_joined', []);
          list.push({ room, password: pw, ts: Date.now() });
          setJSON('chat_rooms_joined', list);
        }
      });
    </script>
  </body>
  </html>
"""


CHAT_HTML = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Chat Room - {{ room }}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/sakura.css/css/sakura.css">
    <style>
      #messages { max-height: 50vh; overflow-y: auto; border: 1px solid #ddd; padding: 0.5rem; }
      .msg { margin: 0.25rem 0; }
      .msg .who { font-weight: bold; }
      #sidebar { border: 1px solid #ddd; padding: 0.5rem; max-width: 320px; }
      .user { display: flex; align-items: center; justify-content: space-between; }
    </style>
  </head>
  <body>
    <h1>Room: {{ room }}</h1>
    <p>Logged in as <strong>{{ username }}</strong>{% if is_owner %} (owner){% endif %}</p>
    <p id="room-state">Room is <span id="lock-state">open</span></p>
    <div style="display:flex; gap:1rem; flex-wrap:wrap;">
      <div style="flex: 2 1 500px;">
        <div id="messages"></div>
        <form id="chat-form">
          <input id="chat-input" type="text" placeholder="Type a message" autocomplete="off" required>
          <button type="submit">Send</button>
        </form>
        <h3>Upload a file</h3>
        <form id="upload-form" method="post" action="{{ url_for('upload_file') }}" enctype="multipart/form-data">
          <input type="file" name="file" required>
          <button type="submit">Upload</button>
        </form>
      </div>
      <div id="sidebar" style="flex: 1 1 280px;">
        <h3>Participants</h3>
        <div id="participants"></div>
        {% if is_owner %}
        <hr>
        <h3>Owner Controls</h3>
        <form id="pw-form" method="post" action="{{ url_for('change_password') }}">
          <label>New Room Password</label>
          <input type="text" name="new_password" required>
          <button type="submit">Change Password</button>
        </form>
        <button id="toggle-lock">Toggle Lock</button>
        <button id="clear-chat">Clear Chat</button>
        <form id="close-form" method="post" action="{{ url_for('close_room') }}">
          <button type="submit" style="background:#c33;color:#fff;">Close Room</button>
        </form>
        {% endif %}
        <hr>
        <h3>Switch Rooms</h3>
        <form id="switch-form" method="post" action="{{ url_for('switch_room') }}">
          <label>Room Code</label>
          <input type="text" name="room" placeholder="room-123" required>
          <label>Password</label>
          <input type="text" name="password" placeholder="Room password" required>
          <button type="submit">Switch</button>
        </form>
        <div>
          <h4>Recent Rooms</h4>
          <div id="recent-switch"></div>
        </div>
      </div>
    </div>

    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js" crossorigin="anonymous"></script>
    <script>
      const socket = io();

      socket.on('connect', () => {
        socket.emit('join', { room: '{{ room }}' });
      });

      const messagesDiv = document.getElementById('messages');
      function addMessage(who, text, fileUrl) {
        const div = document.createElement('div');
        div.className = 'msg';
        const whoSpan = document.createElement('span');
        whoSpan.className = 'who';
        whoSpan.textContent = who + ': ';
        const textSpan = document.createElement('span');
        if (fileUrl) {
          const a = document.createElement('a');
          a.href = fileUrl;
          a.textContent = text;
          a.target = '_blank';
          textSpan.appendChild(a);
        } else {
          textSpan.textContent = text;
        }
        div.appendChild(whoSpan);
        div.appendChild(textSpan);
        messagesDiv.appendChild(div);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
      }

      socket.on('chat_message', (data) => {
        addMessage(data.username || 'unknown', data.text || '', data.file_url || null);
      });

      const form = document.getElementById('chat-form');
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        const input = document.getElementById('chat-input');
        const msg = input.value.trim();
        if (!msg) return;
        socket.emit('chat_message', { text: msg });
        input.value = '';
      });

      const participantsDiv = document.getElementById('participants');
      function renderParticipants(list, isOwner) {
        participantsDiv.innerHTML = '';
        list.forEach(u => {
          const row = document.createElement('div');
          row.className = 'user';
          const name = document.createElement('span');
          name.textContent = u.username + (u.is_owner ? ' (owner)' : '') + (u.is_muted ? ' [muted]' : '');
          row.appendChild(name);
          if (isOwner && !u.is_owner) {
            const btn = document.createElement('button');
            btn.textContent = 'Kick';
            btn.onclick = () => {
              socket.emit('kick_user', { target_sid: u.sid });
            };
            row.appendChild(btn);
            const muteBtn = document.createElement('button');
            muteBtn.textContent = u.is_muted ? 'Unmute' : 'Mute';
            muteBtn.onclick = () => {
              socket.emit(u.is_muted ? 'unmute_user' : 'mute_user', { target_sid: u.sid });
            };
            row.appendChild(muteBtn);
            const banBtn = document.createElement('button');
            banBtn.textContent = 'Ban';
            banBtn.onclick = () => {
              socket.emit('ban_user', { target_sid: u.sid });
            };
            row.appendChild(banBtn);
          }
          participantsDiv.appendChild(row);
        });
      }

      socket.on('participants', (data) => {
        renderParticipants(data.list || [], data.is_owner || false);
        const lockState = document.getElementById('lock-state');
        if (lockState && typeof data.locked !== 'undefined') {
          lockState.textContent = data.locked ? 'locked' : 'open';
        }
      });

      socket.on('kicked', () => {
        alert('You have been kicked by the owner.');
        window.location.href = '{{ url_for('index') }}';
      });

      socket.on('clear_chat', () => {
        messagesDiv.innerHTML = '';
      });

      const toggleLockBtn = document.getElementById('toggle-lock');
      if (toggleLockBtn) {
        toggleLockBtn.onclick = () => socket.emit('toggle_lock', {});
      }
      const clearChatBtn = document.getElementById('clear-chat');
      if (clearChatBtn) {
        clearChatBtn.onclick = () => socket.emit('clear_chat', {});
      }

      // Recent rooms and quick switch (from localStorage)
      function getJSON(key, fallback) {
        try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (_) { return fallback; }
      }
      function setJSON(key, value) { localStorage.setItem(key, JSON.stringify(value)); }

      const hosted = getJSON('chat_rooms_hosted', []);
      const joined = getJSON('chat_rooms_joined', []);
      const recentSwitchEl = document.getElementById('recent-switch');
      function renderSwitchList() {
        recentSwitchEl.innerHTML = '';
        const rooms = [...hosted, ...joined];
        if (!rooms.length) { recentSwitchEl.textContent = 'None'; return; }
        rooms.slice(-10).reverse().forEach(r => {
          const div = document.createElement('div');
          const span = document.createElement('span');
          span.textContent = r.room + ' (last: ' + new Date(r.ts).toLocaleString() + ')';
          div.appendChild(span);
          const btn = document.createElement('button');
          btn.textContent = 'Switch';
          btn.onclick = () => {
            const form = document.getElementById('switch-form');
            form.querySelector('input[name="room"]').value = r.room;
            form.querySelector('input[name="password"]').value = r.password || '';
            form.submit();
          };
          div.appendChild(btn);
          recentSwitchEl.appendChild(div);
        });
      }
      renderSwitchList();
      document.getElementById('switch-form').addEventListener('submit', (e) => {
        const room = e.target.querySelector('input[name="room"]').value.trim();
        const pw = e.target.querySelector('input[name="password"]').value.trim();
        if (room) {
          const list = getJSON('chat_rooms_joined', []);
          list.push({ room, password: pw, ts: Date.now() });
          setJSON('chat_rooms_joined', list);
        }
      });
    </script>
  </body>
  </html>
"""


def _safe_room(code: str) -> str:
    return ''.join(ch for ch in (code or '').strip() if ch.isalnum() or ch in ('-', '_'))


@app.get('/')
def index():
    return render_template_string(INDEX_HTML)


@app.post('/host')
def host():
    username = (request.form.get('username') or '').strip()
    room = _safe_room(request.form.get('room') or '')
    password = (request.form.get('password') or '').strip()
    if not username or not room or not password:
        flash('All fields are required to host a room.')
        return redirect(url_for('index'))
    if room in ROOMS:
        flash('Room code already exists. Choose another.')
        return redirect(url_for('index'))
    ROOMS[room] = { 'password': password, 'owner_sid': None, 'locked': False, 'banned': set(), 'muted': set(), 'participants': {} }
    session['username'] = username
    session['room'] = room
    session['is_owner'] = True
    return redirect(url_for('chat', room=room))


@app.post('/join')
def join():
    username = (request.form.get('username') or '').strip()
    room = _safe_room(request.form.get('room') or '')
    password = (request.form.get('password') or '').strip()
    if not username or not room or not password:
        flash('All fields are required to join.')
        return redirect(url_for('index'))
    if room not in ROOMS:
        flash('Room not found. Ask the owner to host first.')
        return redirect(url_for('index'))
    if ROOMS[room]['locked']:
        flash('Room is locked by the owner.')
        return redirect(url_for('index'))
    if username in ROOMS[room]['banned']:
        flash('You are banned from this room.')
        return redirect(url_for('index'))
    if ROOMS[room]['password'] != password:
        flash('Incorrect room password.')
        return redirect(url_for('index'))
    session['username'] = username
    session['room'] = room
    session['is_owner'] = False
    return redirect(url_for('chat', room=room))


@app.get('/chat/<room>')
def chat(room):
    room = _safe_room(room)
    if not session.get('username') or session.get('room') != room:
        return redirect(url_for('index'))
    return render_template_string(CHAT_HTML, username=session['username'], room=room, is_owner=bool(session.get('is_owner')))


@app.post('/upload')
def upload_file():
    username = session.get('username')
    room = _safe_room(session.get('room', ''))
    if not username or not room:
        flash('Not authorized')
        return redirect(url_for('index'))
    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('chat', room=room))
    f = request.files['file']
    if f.filename == '':
        flash('No selected file')
        return redirect(url_for('chat', room=room))
    room_path = os.path.join(app.config['UPLOAD_FOLDER'], room)
    os.makedirs(room_path, exist_ok=True)
    filename = os.path.basename(f.filename)
    save_path = os.path.join(room_path, filename)
    f.save(save_path)
    file_url = url_for('serve_file', room=room, filename=filename)
    socketio.emit('chat_message', {
        'username': username,
        'room': room,
        'text': f"uploaded a file: {filename}",
        'file_url': file_url,
    }, room=room)
    return redirect(url_for('chat', room=room))


@app.get('/files/<room>/<path:filename>')
def serve_file(room, filename):
    room = _safe_room(room)
    room_path = os.path.join(app.config['UPLOAD_FOLDER'], room)
    return send_from_directory(room_path, filename)


@app.post('/admin/change_password')
def change_password():
    room = _safe_room(session.get('room', ''))
    if not room or room not in ROOMS:
        flash('No active room')
        return redirect(url_for('index'))
    if not session.get('is_owner'):
        flash('Only owner can change password')
        return redirect(url_for('chat', room=room))
    new_pw = (request.form.get('new_password') or '').strip()
    if not new_pw:
        flash('New password required')
        return redirect(url_for('chat', room=room))
    ROOMS[room]['password'] = new_pw
    flash('Room password updated')
    return redirect(url_for('chat', room=room))


@app.post('/admin/close_room')
def close_room():
    room = _safe_room(session.get('room', ''))
    if not room or room not in ROOMS:
        flash('No active room')
        return redirect(url_for('index'))
    if not session.get('is_owner'):
        flash('Only owner can close room')
        return redirect(url_for('chat', room=room))
    # Disconnect everyone and remove room
    parts = list(ROOMS[room]['participants'].keys())
    for sid in parts:
        socketio.emit('kicked', {}, to=sid)
        disconnect(sid)
    ROOMS.pop(room, None)
    session.pop('room', None)
    session.pop('is_owner', None)
    flash('Room closed')
    return redirect(url_for('index'))


@app.post('/switch_room')
def switch_room():
    username = session.get('username')
    current_room = _safe_room(session.get('room', ''))
    room = _safe_room(request.form.get('room') or '')
    password = (request.form.get('password') or '').strip()
    if not username or not room or not password:
        flash('All fields are required to switch rooms')
        return redirect(url_for('chat', room=current_room or ''))
    if room not in ROOMS:
        flash('Target room not found')
        return redirect(url_for('chat', room=current_room or ''))
    if ROOMS[room]['locked']:
        flash('Target room is locked by the owner')
        return redirect(url_for('chat', room=current_room or ''))
    if username in ROOMS[room]['banned']:
        flash('You are banned from that room')
        return redirect(url_for('chat', room=current_room or ''))
    if ROOMS[room]['password'] != password:
        flash('Incorrect room password')
        return redirect(url_for('chat', room=current_room or ''))
    # Update session to new room
    session['room'] = room
    session['is_owner'] = False
    return redirect(url_for('chat', room=room))


def _broadcast_participants(room: str):
    parts = ROOMS[room]['participants']
    muted = ROOMS[room]['muted']
    lst = [ { 'sid': sid, 'username': info['username'], 'is_owner': bool(info.get('is_owner')), 'is_muted': sid in muted } for sid, info in parts.items() ]
    for sid in list(parts.keys()):
        # Send owner flag relative to each recipient
        is_owner = bool(parts.get(sid, {}).get('is_owner'))
        socketio.emit('participants', { 'list': lst, 'is_owner': is_owner, 'locked': bool(ROOMS[room]['locked']) }, to=sid)


@socketio.on('join')
def on_join(data):
    username = session.get('username')
    room = _safe_room(session.get('room', ''))
    if not username or not room or room not in ROOMS:
        return
    join_room(room)
    # Register participant
    is_owner = bool(session.get('is_owner'))
    ROOMS[room]['participants'][request.sid] = { 'username': username, 'is_owner': is_owner }
    # Assign owner_sid if hosting and not set
    if is_owner and not ROOMS[room]['owner_sid']:
        ROOMS[room]['owner_sid'] = request.sid
    emit('chat_message', { 'username': 'system', 'room': room, 'text': f'{username} joined the room.' }, room=room)
    _broadcast_participants(room)


@socketio.on('disconnect')
def on_disconnect():
    room = _safe_room(session.get('room', ''))
    username = session.get('username')
    if room in ROOMS and request.sid in ROOMS[room]['participants']:
        was_owner = bool(ROOMS[room]['participants'][request.sid].get('is_owner'))
        ROOMS[room]['participants'].pop(request.sid, None)
        # Transfer ownership if owner left
        if was_owner and ROOMS[room]['owner_sid'] == request.sid:
            ROOMS[room]['owner_sid'] = None
            # Assign first remaining as new owner
            for sid, info in ROOMS[room]['participants'].items():
                ROOMS[room]['owner_sid'] = sid
                info['is_owner'] = True
                break
        emit('chat_message', { 'username': 'system', 'room': room, 'text': f'{username} left the room.' }, room=room)
        if room in ROOMS:
            _broadcast_participants(room)


@socketio.on('chat_message')
def handle_chat_message(data):
    username = session.get('username')
    room = _safe_room(session.get('room', ''))
    text = (data or {}).get('text', '').strip()
    if not username or not room or room not in ROOMS or not text:
        return
    # Block muted senders
    if request.sid in ROOMS[room]['muted']:
        emit('chat_message', { 'username': 'system', 'room': room, 'text': 'You are muted by the owner.' }, to=request.sid)
        return
    emit('chat_message', { 'username': username, 'room': room, 'text': text }, room=room)


@socketio.on('kick_user')
def handle_kick(data):
    room = _safe_room(session.get('room', ''))
    kicker_sid = request.sid
    target_sid = (data or {}).get('target_sid')
    if not room or room not in ROOMS:
        return
    # Only owner can kick
    if ROOMS[room]['owner_sid'] != kicker_sid:
        return
    if target_sid and target_sid in ROOMS[room]['participants']:
        target_name = ROOMS[room]['participants'][target_sid]['username']
        socketio.emit('kicked', {}, to=target_sid)
        disconnect(target_sid)
        emit('chat_message', { 'username': 'system', 'room': room, 'text': f'{target_name} was kicked by the owner.' }, room=room)
        _broadcast_participants(room)


@socketio.on('mute_user')
def handle_mute(data):
    room = _safe_room(session.get('room', ''))
    owner_sid = request.sid
    target_sid = (data or {}).get('target_sid')
    if not room or room not in ROOMS:
        return
    if ROOMS[room]['owner_sid'] != owner_sid:
        return
    if target_sid and target_sid in ROOMS[room]['participants']:
        ROOMS[room]['muted'].add(target_sid)
        target_name = ROOMS[room]['participants'][target_sid]['username']
        emit('chat_message', { 'username': 'system', 'room': room, 'text': f'{target_name} was muted.' }, room=room)
        _broadcast_participants(room)


@socketio.on('unmute_user')
def handle_unmute(data):
    room = _safe_room(session.get('room', ''))
    owner_sid = request.sid
    target_sid = (data or {}).get('target_sid')
    if not room or room not in ROOMS:
        return
    if ROOMS[room]['owner_sid'] != owner_sid:
        return
    if target_sid and target_sid in ROOMS[room]['participants']:
        ROOMS[room]['muted'].discard(target_sid)
        target_name = ROOMS[room]['participants'][target_sid]['username']
        emit('chat_message', { 'username': 'system', 'room': room, 'text': f'{target_name} was unmuted.' }, room=room)
        _broadcast_participants(room)


@socketio.on('ban_user')
def handle_ban(data):
    room = _safe_room(session.get('room', ''))
    owner_sid = request.sid
    target_sid = (data or {}).get('target_sid')
    if not room or room not in ROOMS:
        return
    if ROOMS[room]['owner_sid'] != owner_sid:
        return
    if target_sid and target_sid in ROOMS[room]['participants']:
        target_name = ROOMS[room]['participants'][target_sid]['username']
        ROOMS[room]['banned'].add(target_name)
        socketio.emit('kicked', {}, to=target_sid)
        disconnect(target_sid)
        emit('chat_message', { 'username': 'system', 'room': room, 'text': f'{target_name} was banned.' }, room=room)
        _broadcast_participants(room)


@socketio.on('toggle_lock')
def handle_toggle_lock():
    room = _safe_room(session.get('room', ''))
    owner_sid = request.sid
    if not room or room not in ROOMS:
        return
    if ROOMS[room]['owner_sid'] != owner_sid:
        return
    ROOMS[room]['locked'] = not ROOMS[room]['locked']
    emit('chat_message', { 'username': 'system', 'room': room, 'text': 'Room is now ' + ('locked' if ROOMS[room]['locked'] else 'open') + '.' }, room=room)
    _broadcast_participants(room)


@socketio.on('clear_chat')
def handle_clear_chat():
    room = _safe_room(session.get('room', ''))
    owner_sid = request.sid
    if not room or room not in ROOMS:
        return
    if ROOMS[room]['owner_sid'] != owner_sid:
        return
    socketio.emit('clear_chat', {}, room=room)


if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '5000'))
    socketio.run(app, host=host, port=port)