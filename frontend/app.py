import os
import time
import uuid
import json
import re
import requests
import streamlit as st

# --------------------
# Config
# --------------------
st.set_page_config(page_title="RAG Assistant", page_icon="🤖", layout="wide")

BACKEND_UPLOAD_URL = os.getenv(
    "BACKEND_UPLOAD_URL", "http://localhost:8000/upload")
BACKEND_CHAT_URL = os.getenv("BACKEND_CHAT_URL", "http://localhost:8002/chat")
BACKEND_USER_URL = os.getenv("BACKEND_USER_URL", "http://localhost:8003")

# --------------------
# Session State
# --------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "chat_sessions" not in st.session_state:
    st.session_state.chat_sessions = []
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None
if "uploaded_docs" not in st.session_state:
    st.session_state.uploaded_docs = []
if "upload_events" not in st.session_state:
    st.session_state.upload_events = []
if "upload_widget_nonce" not in st.session_state:
    st.session_state.upload_widget_nonce = 0
if "theme_choice" not in st.session_state:
    base_theme = (st.get_option("theme.base") or "dark").lower()
    st.session_state.theme_choice = "Light" if base_theme == "light" else "Dark"

THEME_PALETTES = {
    "dark": {
        "app_bg": "#0f1115",
        "sidebar_bg": "#151923",
        "surface_bg": "#171b24",
        "panel_bg": "#1f2430",
        "input_bg": "#232938",
        "border": "#31384a",
        "text": "#f3f4f6",
        "muted_text": "#a9b1c3",
        "accent": "#5b6cff",
        "button_bg": "linear-gradient(135deg, #5b6cff 0%, #7b4dff 100%)",
        "button_hover": "linear-gradient(135deg, #4d5eff 0%, #6840e6 100%)",
        "button_border": "transparent",
        "button_text": "#ffffff",
        "scroll_track": "#171b24",
        "user_chat_bg": "linear-gradient(135deg, #5b6cff 0%, #7b4dff 100%)",
        "assistant_chat_bg": "#232938",
    },
    "light": {
        "app_bg": "#f5f7fb",
        "sidebar_bg": "#ffffff",
        "surface_bg": "#ffffff",
        "panel_bg": "#eef2f6",
        "input_bg": "#ffffff",
        "border": "#d6dce8",
        "text": "#111827",
        "muted_text": "#5b6472",
        "accent": "#2563eb",
        "button_bg": "linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)",
        "button_hover": "linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%)",
        "button_border": "transparent",
        "button_text": "#ffffff",
        "scroll_track": "#e5e7eb",
        "user_chat_bg": "linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)",
        "assistant_chat_bg": "#f3f4f6",
    },
}


def get_theme_mode() -> str:
    choice = st.session_state.get("theme_choice", "Dark")
    return "light" if str(choice).lower() == "light" else "dark"


def inject_theme_styles(theme_mode: str) -> None:
    palette = THEME_PALETTES[theme_mode]
    st.markdown(
        f"""
        <style>
            .stApp {{ background: {palette['app_bg']}; color: {palette['text']}; }}
            [data-testid='stSidebar'] {{ background: {palette['sidebar_bg']}; border-right: 1px solid {palette['border']}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_theme_styles(get_theme_mode())

# --------------------
# Helpers
# --------------------
AUTH_STORE_PATH = os.path.join(os.path.dirname(__file__), "user_data.json")

DEFAULT_LOCAL_USERS = {
    "admin": {"password": "admin123"},
    "testuser": {"password": "1234"},
}


def _normalize_user_record(record: dict) -> dict:
    if not isinstance(record, dict):
        record = {}
    return {
        "password": record.get("password", ""),
        "chat_sessions": record.get("chat_sessions", []),
        "uploaded_docs": record.get("uploaded_docs", []),
        "upload_events": record.get("upload_events", []),
    }


def load_local_users() -> dict:
    try:
        with open(AUTH_STORE_PATH, "r", encoding="utf-8") as f:
            users = json.load(f)
        if not isinstance(users, dict):
            users = {}
    except (FileNotFoundError, json.JSONDecodeError):
        users = {}

    normalized = {u: _normalize_user_record(r) for u, r in users.items()}
    for u, defaults in DEFAULT_LOCAL_USERS.items():
        normalized.setdefault(u, _normalize_user_record({}))
        normalized[u].setdefault("password", defaults["password"])
        normalized[u].setdefault("chat_sessions", [])
        normalized[u].setdefault("uploaded_docs", [])
        normalized[u].setdefault("upload_events", [])
    return normalized


def save_local_users(users: dict) -> None:
    with open(AUTH_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)


def persist_local_user(
    username: str,
    password=None,
    chat_sessions=None,
    uploaded_docs=None,
    upload_events=None,
):
    users = load_local_users()
    record = _normalize_user_record(users.get(username, {}))

    if password is not None:
        record["password"] = password
    if chat_sessions is not None:
        record["chat_sessions"] = chat_sessions
    if uploaded_docs is not None:
        record["uploaded_docs"] = uploaded_docs
    if upload_events is not None:
        record["upload_events"] = upload_events

    users[username] = record
    save_local_users(users)
    return record


def get_local_user(username: str) -> dict | None:
    return load_local_users().get(username)


def request_user_service(method: str, endpoint: str, data=None, timeout: int = 8):
    # In this repo, user_service may not be fully implemented; keep robust fallbacks.
    base_urls = []
    env_url = os.getenv("BACKEND_USER_URL", BACKEND_USER_URL).rstrip("/")
    if env_url:
        base_urls.append(env_url)
    base_urls.append("http://localhost:8003")
    base_urls.append("http://user_service:8003")

    last_error = None
    for base_url in dict.fromkeys(base_urls):
        url = f"{base_url}{endpoint}"
        try:
            if method == "GET":
                return requests.get(url, timeout=timeout)
            if method == "POST":
                return requests.post(url, json=data, timeout=timeout)
            if method == "PUT":
                return requests.put(url, json=data, timeout=timeout)
            st.error(f"Unsupported API method: {method}")
            return None
        except requests.RequestException as exc:
            last_error = exc

    if last_error is not None:
        st.error(f"Could not connect to user service: {last_error}")
    return None


def login_or_register(username: str, password: str):
    # Local fallback auth (production-ready user_service integration is not guaranteed in this repo).
    local_user = get_local_user(username)
    if local_user and local_user.get("password") == password:
        set_authenticated_user(username, chat_sessions=local_user.get("chat_sessions", []), uploaded_docs=local_user.get(
            "uploaded_docs", []), upload_events=local_user.get("upload_events", []))
        return

    # Optional: try user_service if reachable.
    resp = request_user_service(
        "POST", "/login", data={"username": username, "password": password}, timeout=8)
    if resp is not None and resp.ok:
        payload = resp.json()
        uploaded_docs = [doc.get("file_id") for doc in payload.get(
            "documents", []) if doc.get("file_id")]
        upload_events = [
            {
                "file_id": doc.get("file_id", ""),
                "filename": doc.get("filename", doc.get("file_id", "")),
                "uploaded_at": doc.get("uploaded_at", ""),
                "status": "uploaded",
                "ingestion_triggered": True,
                "warning": "",
            }
            for doc in payload.get("documents", [])
            if doc.get("file_id")
        ]
        persist_local_user(username, password=password, chat_sessions=payload.get(
            "chat_sessions", []), uploaded_docs=uploaded_docs, upload_events=upload_events)
        set_authenticated_user(username, chat_sessions=payload.get(
            "chat_sessions", []), uploaded_docs=uploaded_docs, upload_events=upload_events)
        return

    st.error("Incorrect username/password")


def set_authenticated_user(username: str, chat_sessions=None, uploaded_docs=None, upload_events=None):
    st.session_state.logged_in = True
    st.session_state.username = username
    st.session_state.chat_sessions = chat_sessions or []
    st.session_state.uploaded_docs = uploaded_docs or []
    st.session_state.upload_events = upload_events or []

    if st.session_state.chat_sessions:
        st.session_state.current_session_id = st.session_state.chat_sessions[0]["id"]
    else:
        create_new_chat()

    persist_local_user(
        username,
        chat_sessions=st.session_state.chat_sessions,
        uploaded_docs=st.session_state.uploaded_docs,
        upload_events=st.session_state.upload_events,
        password=(get_local_user(username) or {}).get("password", ""),
    )
    st.rerun()


def create_new_chat():
    new_session = {
        "id": str(uuid.uuid4()),
        "title": "New Chat",
        "messages": [],
        "selected_docs": [],
    }
    st.session_state.chat_sessions.insert(0, new_session)
    st.session_state.current_session_id = new_session["id"]
    st.session_state.upload_widget_nonce += 1

    persist_local_user(
        st.session_state.username,
        chat_sessions=st.session_state.chat_sessions,
        uploaded_docs=st.session_state.uploaded_docs,
        upload_events=st.session_state.upload_events,
        password=(get_local_user(st.session_state.username)
                  or {}).get("password", ""),
    )


def logout():
    if st.session_state.username:
        persist_local_user(
            st.session_state.username,
            chat_sessions=st.session_state.chat_sessions,
            uploaded_docs=st.session_state.uploaded_docs,
            upload_events=st.session_state.upload_events,
            password=(get_local_user(st.session_state.username)
                      or {}).get("password", ""),
        )

    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.chat_sessions = []
    st.session_state.current_session_id = None
    st.session_state.uploaded_docs = []
    st.session_state.upload_events = []
    st.session_state.upload_widget_nonce += 1
    st.rerun()


def load_chat_session(session_id: str):
    st.session_state.current_session_id = session_id
    st.session_state.upload_widget_nonce += 1


def get_current_chat_history():
    if not st.session_state.current_session_id:
        return []
    for session in st.session_state.chat_sessions:
        if session["id"] == st.session_state.current_session_id:
            return session.get("messages", [])
    return []


def set_current_chat_history(messages):
    if not st.session_state.current_session_id:
        return
    for session in st.session_state.chat_sessions:
        if session["id"] == st.session_state.current_session_id:
            session["messages"] = messages
            break


def get_current_selected_docs():
    if not st.session_state.current_session_id:
        return []
    for session in st.session_state.chat_sessions:
        if session["id"] == st.session_state.current_session_id:
            return session.get("selected_docs", [])
    return []


def set_current_selected_docs(selected_docs):
    if not st.session_state.current_session_id:
        return
    for session in st.session_state.chat_sessions:
        if session["id"] == st.session_state.current_session_id:
            session["selected_docs"] = selected_docs
            break


def upload_to_backend(uploaded_file):
    files = {"file": (uploaded_file.name,
                      uploaded_file.getvalue(), uploaded_file.type)}
    try:
        response = requests.post(BACKEND_UPLOAD_URL, files=files, timeout=60)
    except requests.exceptions.ConnectionError:
        st.error("Could not connect to Upload Service")
        return False

    if response.status_code != 200:
        st.error(f"Upload failed: {response.text}")
        return False

    data = response.json()
    file_id = data.get("file_id", uploaded_file.name)

    if file_id not in st.session_state.uploaded_docs:
        st.session_state.uploaded_docs.append(file_id)

    st.session_state.upload_events.insert(
        0,
        {
            "file_id": file_id,
            "filename": uploaded_file.name,
            "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "uploaded",
            "ingestion_triggered": bool(data.get("ingestion_triggered", False)),
            "warning": data.get("warning", ""),
        },
    )

    persist_local_user(
        st.session_state.username,
        chat_sessions=st.session_state.chat_sessions,
        uploaded_docs=st.session_state.uploaded_docs,
        upload_events=st.session_state.upload_events,
        password=(get_local_user(st.session_state.username)
                  or {}).get("password", ""),
    )

    return True


def query_retrieval_service(query: str, selected_docs: list[str]):
    payload = {"query": query, "selected_docs": selected_docs}
    try:
        response = requests.post(BACKEND_CHAT_URL, json=payload, timeout=60)
    except requests.exceptions.ConnectionError:
        return "Could not connect to Retrieval Service"

    if response.status_code != 200:
        return f"Error: {response.text}"

    data = response.json()
    return data.get("answer", "")


def save_chat_to_backend():
    # If user_service exists later, this can persist to Mongo.
    return


# --------------------
# UI
# --------------------
if not st.session_state.logged_in:
    palette = THEME_PALETTES[get_theme_mode()]
    st.title("🔮 RAG Assistant")

    tab_login, tab_signup = st.tabs(["Sign In", "Sign Up"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("Username", key="login_user")
            password = st.text_input(
                "Password", type="password", key="login_pass")
            submit = st.form_submit_button("Sign In", use_container_width=True)
            if submit:
                login_or_register(username, password)

    with tab_signup:
        st.info("Sign up is optional. Local accounts: admin/admin123, testuser/1234")
        with st.form("signup_form"):
            new_username = st.text_input("Choose Username", key="signup_user")
            new_password = st.text_input(
                "Choose Password", type="password", key="signup_pass")
            if st.form_submit_button("Create Account", use_container_width=True):
                # Minimal local registration: keep it safe by not auto-creating without explicit logic in this repo.
                st.error(
                    "User service registration not implemented; use Sign In with existing local accounts.")

else:
    palette = THEME_PALETTES[get_theme_mode()]

    with st.sidebar:
        st.markdown(
            f"""
            <div style='padding: 10px;'>
              <div style='font-size: 18px; font-weight: 600; color: {palette['text']}; margin-bottom: 5px;'>{st.session_state.username}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.radio("Theme", ["Dark", "Light"],
                 key="theme_choice", horizontal=True)

        if st.button("＋ New Chat", use_container_width=True):
            create_new_chat()

        st.markdown("---")
        st.subheader("Chats")
        if not st.session_state.chat_sessions:
            st.caption("No chats yet")
        else:
            for session in st.session_state.chat_sessions:
                title = session.get("title", "New Chat")
                st.button(
                    title,
                    key=f"chat_{session['id']}",
                    use_container_width=True,
                    on_click=load_chat_session,
                    args=(session["id"],),
                )

        st.markdown("---")
        st.subheader("Sources")

        uploaded_file = st.file_uploader(
            "Add Source",
            type=["txt", "md"],
            label_visibility="collapsed",
            key=f"source_uploader_{st.session_state.upload_widget_nonce}",
        )

        if uploaded_file is not None:
            if st.button("↑ Upload", use_container_width=True):
                with st.spinner("Uploading..."):
                    ok = upload_to_backend(uploaded_file)
                    if ok:
                        st.success("Added!")
                        time.sleep(0.5)
                        st.rerun()

        if st.session_state.uploaded_docs:
            selected_docs = st.multiselect(
                "Select sources for this chat:",
                st.session_state.uploaded_docs,
                default=get_current_selected_docs(),
                key=f"selected_docs_{st.session_state.current_session_id}",
            )
            set_current_selected_docs(selected_docs)
        else:
            st.caption("Upload a document first")

        st.divider()
        if st.button("Log out", use_container_width=True):
            logout()

    # Main chat area
    st.title("💬 Document Chat")

    current_chat = get_current_chat_history()
    selected_docs = get_current_selected_docs()

    for msg in current_chat:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("Ask about your sources...")
    if prompt:
        if not selected_docs:
            st.warning("Please select at least one source")
        else:
            current_chat.append({"role": "user", "content": prompt})
            set_current_chat_history(current_chat)

            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    ai_response = query_retrieval_service(
                        prompt, selected_docs)
                    st.markdown(ai_response)

            current_chat.append({"role": "assistant", "content": ai_response})
            set_current_chat_history(current_chat)

            save_chat_to_backend()
            st.rerun()
