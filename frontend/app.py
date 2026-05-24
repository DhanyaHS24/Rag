import os
import time
import uuid
import re
import requests
import streamlit as st


st.set_page_config(page_title="RAG Assistant", page_icon="🤖", layout="wide")

BACKEND_UPLOAD_URL = os.getenv(
    "BACKEND_UPLOAD_URL", "http://localhost:8004/upload")
BACKEND_CHAT_URL = os.getenv("BACKEND_CHAT_URL", "http://localhost:8002/chat")
BACKEND_USER_URL = os.getenv("BACKEND_USER_URL", "http://localhost:8003")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "token" not in st.session_state:
    st.session_state.token = ""
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
            .stApp {{
                background: {palette['app_bg']};
                color: {palette['text']};
            }}

            header[data-testid='stHeader'],
            [data-testid='stHeader'] {{
                background: {palette['surface_bg']} !important;
                color: {palette['text']} !important;
                border-bottom: 1px solid {palette['border']} !important;
                box-shadow: 0 1px 0 rgba(17, 24, 39, 0.03) !important;
            }}

            [data-testid='stDecoration'] {{
                background: {palette['button_bg']} !important;
                height: 3px !important;
            }}

            [data-testid='stToolbar'],
            [data-testid='stToolbarActions'],
            [data-testid='stDeployButton'],
            [data-testid='stMainMenu'] {{
                color: {palette['muted_text']} !important;
            }}

            [data-testid='baseButton-header'],
            [data-testid='baseButton-headerNoPadding'] {{
                color: {palette['muted_text']} !important;
                background: transparent !important;
            }}

            [data-testid='stAppViewContainer'] {{
                background: {palette['app_bg']} !important;
            }}

            [data-testid='stAppViewBlockContainer'] {{
                padding-top: 5rem;
                padding-bottom: 7rem;
            }}

            [data-testid='stSidebar'] {{
                background: {palette['sidebar_bg']};
                border-right: 1px solid {palette['border']};
            }}

            [data-testid='stSidebar'] > div {{
                background: {palette['sidebar_bg']};
            }}

            .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
            p, .stMarkdown, .stCaption, .stSubheader {{
                color: {palette['text']};
            }}

            .stTextInput label, .stTextArea label {{
                color: {palette['text']} !important;
            }}

            .stTextInput input, .stTextArea textarea,
            [data-testid='stChatInput'] textarea {{
                background: {palette['input_bg']} !important;
                color: {palette['text']} !important;
                border: 1px solid {palette['border']} !important;
                border-radius: 8px !important;
            }}

            .stTextInput input::placeholder, .stTextArea textarea::placeholder,
            [data-testid='stChatInput'] textarea::placeholder {{
                color: {palette['muted_text']} !important;
                opacity: 1;
            }}

            .stButton > button {{
                background: {palette['button_bg']};
                color: {palette['button_text']};
                border: 1px solid {palette['button_border']};
                border-radius: 8px;
                font-weight: 600;
            }}
            .stButton > button:hover {{
                background: {palette['button_hover']};
            }}

            .stFormSubmitButton > button {{
                background: {palette['button_bg']} !important;
                color: {palette['button_text']} !important;
                border: 1px solid {palette['button_border']} !important;
                border-radius: 8px !important;
                font-weight: 600 !important;
            }}
            .stFormSubmitButton > button:hover {{
                background: {palette['button_hover']} !important;
            }}

            .stTabs [data-baseweb="tab-list"] {{
                background: {palette['panel_bg']};
                border-radius: 8px;
                padding: 4px;
            }}
            .stTabs [data-baseweb="tab"] {{
                color: {palette['muted_text']} !important;
            }}
            .stTabs [aria-selected="true"] {{
                color: {palette['accent']} !important;
                background: {palette['app_bg']};
                border-radius: 6px;
            }}

            [data-testid="stChatMessage"] {{
                background: {palette['panel_bg']};
                border-radius: 12px;
                padding: 12px;
                margin: 8px 0;
            }}

            [data-testid='stBottomBlockContainer'],
            [data-testid='stChatFloatingInputContainer'] {{
                background: {palette['surface_bg']} !important;
                border-top: 1px solid {palette['border']};
                box-shadow: 0 -10px 30px rgba(17, 24, 39, 0.06);
            }}

            [data-testid='stChatInput'] {{
                background: transparent !important;
            }}

            [data-testid='stSidebar'] .stButton > button {{
                background: transparent;
                color: {palette['text']};
                border: 1px solid {palette['border']};
            }}
            [data-testid='stSidebar'] .stButton > button:hover {{
                background: {palette['panel_bg']};
                border-color: {palette['accent']};
                color: {palette['accent']};
            }}

            [data-testid='stSidebar'] .stSubheader {{
                color: {palette['text']} !important;
            }}
            [data-testid='stSidebar'] .stCaption {{
                color: {palette['muted_text']} !important;
            }}

            .stMultiSelect [data-baseweb="select"] {{
                background: {palette['input_bg']};
            }}

            [data-testid='stFileUploader'] {{
                color: {palette['text']};
            }}

            [data-testid='stFileUploaderDropzone'] {{
                background: {palette['surface_bg']} !important;
                color: {palette['text']} !important;
                border: 1px dashed {palette['border']} !important;
                border-radius: 12px !important;
            }}

            [data-testid='stFileUploaderDropzone'] button {{
                background: {palette['panel_bg']} !important;
                color: {palette['text']} !important;
                border: 1px solid {palette['border']} !important;
            }}

            [data-testid='stFileUploaderDropzone'] small,
            [data-testid='stFileUploaderDropzone'] p {{
                color: {palette['muted_text']} !important;
            }}

            .stAlert {{
                background: {palette['panel_bg']};
                color: {palette['text']};
                border: 1px solid {palette['border']};
                border-radius: 8px;
            }}

            .stForm {{
                border: 1px solid {palette['border']};
                border-radius: 12px;
                padding: 24px;
                background: {palette['surface_bg']};
            }}

            .psc {{
                margin-top: 6px;
                margin-bottom: 16px;
            }}
            .psc-bar {{
                height: 5px;
                border-radius: 3px;
                width: 0%;
                transition: width 0.3s, background-color 0.3s;
                background: #ddd;
            }}
            .psc-text {{
                font-size: 12px;
                margin-top: 4px;
                font-weight: 500;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_theme_styles(get_theme_mode())


def inject_password_strength_js():
    st.markdown(
        """
        <script>
        (function() {
            function checkStrength(pw) {
                if (!pw) return -1;
                var score = 0;
                if (pw.length >= 8) score++;
                if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
                if (/[0-9]/.test(pw)) score++;
                if (/[^A-Za-z0-9]/.test(pw)) score++;
                return score;
            }
            function getStrengthInfo(score) {
                if (score === -1) return { label: '', color: '#ddd', width: '0%' };
                var levels = [
                    { label: 'Weak', color: '#ef4444', width: '25%' },
                    { label: 'Fair', color: '#f59e0b', width: '50%' },
                    { label: 'Good', color: '#84cc16', width: '75%' },
                    { label: 'Strong', color: '#22c55e', width: '100%' }
                ];
                return levels[score] || levels[0];
            }
            function watchInputs() {
                var uid = 0;
                var inputs = document.querySelectorAll('input[type="password"]');
                inputs.forEach(function(input) {
                    if (input.dataset.strengthWatched) return;
                    input.dataset.strengthWatched = 'true';
                    uid++;
                    var cid = 'psc-' + uid;
                    var container = document.createElement('div');
                    container.id = cid;
                    container.className = 'psc';
                    container.style.display = 'none';
                    var bar = document.createElement('div');
                    bar.className = 'psc-bar';
                    var text = document.createElement('div');
                    text.className = 'psc-text';
                    container.appendChild(bar);
                    container.appendChild(text);
                    input.parentElement.appendChild(container);

                    input.addEventListener('input', function() {
                        var info = getStrengthInfo(checkStrength(this.value));
                        bar.style.width = info.width;
                        bar.style.backgroundColor = info.color;
                        text.textContent = info.label;
                        text.style.color = info.color;
                        container.style.display = info.label ? 'block' : 'none';
                    });
                });
            }
            watchInputs();
            setInterval(watchInputs, 1200);
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )


def request_user_service(method: str, endpoint: str, data=None, timeout: int = 8):
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
            headers = {}
            token = st.session_state.get("token", "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            if method == "GET":
                return requests.get(url, headers=headers, timeout=timeout)
            if method == "POST":
                return requests.post(url, json=data, headers=headers, timeout=timeout)
            if method == "PUT":
                return requests.put(url, json=data, headers=headers, timeout=timeout)
            st.error(f"Unsupported API method: {method}")
            return None
        except requests.RequestException as exc:
            last_error = exc

    if last_error is not None:
        st.error(f"Could not connect to user service: {last_error}")
    return None


def login_or_register(username: str, password: str):
    resp = request_user_service(
        "POST", "/login", data={"username": username, "password": password}, timeout=8)
    if resp is not None and resp.ok:
        payload = resp.json()
        token = payload.get("token", "")
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
        set_authenticated_user(username, token=token, chat_sessions=payload.get(
            "chat_sessions", []), uploaded_docs=uploaded_docs, upload_events=upload_events)
        return

    st.error("Incorrect username/password")


def password_strength_score(password: str) -> int:
    score = 0
    if len(password) >= 8:
        score += 1
    if re.search(r"[A-Z]", password) and re.search(r"[a-z]", password):
        score += 1
    if re.search(r"[0-9]", password):
        score += 1
    if re.search(r"[^A-Za-z0-9]", password):
        score += 1
    return score


def register_user(username: str, password: str):
    if password_strength_score(password) < 2:
        st.error("Password is too weak. Use at least 8 characters with a mix of upper/lower case letters, numbers, and symbols.")
        return
    resp = request_user_service(
        "POST", "/register", data={"username": username, "password": password}, timeout=8)
    if resp is not None and resp.ok:
        payload = resp.json()
        token = payload.get("token", "")
        set_authenticated_user(username, token=token, chat_sessions=[], uploaded_docs=[], upload_events=[])
        return

    if resp is not None:
        st.error(f"Sign up failed: {resp.text}")
        return


def set_authenticated_user(username: str, token: str = "", chat_sessions=None, uploaded_docs=None, upload_events=None):
    st.session_state.logged_in = True
    st.session_state.username = username
    st.session_state.token = token
    st.session_state.chat_sessions = chat_sessions or []
    st.session_state.uploaded_docs = uploaded_docs or []
    st.session_state.upload_events = upload_events or []

    if st.session_state.chat_sessions:
        st.session_state.current_session_id = st.session_state.chat_sessions[0]["id"]
    else:
        create_new_chat()

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


def logout():
    save_chat_to_backend()
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.token = ""
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


def make_chat_title(prompt: str, max_length: int = 38) -> str:
    title = " ".join(prompt.strip().split())
    if not title:
        return "New Chat"
    return title if len(title) <= max_length else f"{title[:max_length - 1].rstrip()}…"


def get_chat_display_title(session: dict) -> str:
    title = session.get("title", "New Chat")
    if title and title != "New Chat":
        return title
    for message in session.get("messages", []):
        if message.get("role") == "user" and message.get("content"):
            return make_chat_title(message["content"])
    return "New Chat"


def update_current_chat_title(prompt: str):
    if not st.session_state.current_session_id:
        return
    for session in st.session_state.chat_sessions:
        if session["id"] == st.session_state.current_session_id:
            if session.get("title", "New Chat") == "New Chat":
                session["title"] = make_chat_title(prompt)
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


def get_doc_display_name(file_id: str) -> str:
    for event in st.session_state.upload_events:
        if event.get("file_id") == file_id:
            return event.get("filename") or file_id
    return file_id


def upload_to_backend(uploaded_file):
    files = {"file": (uploaded_file.name,
                      uploaded_file.getvalue(), uploaded_file.type)}
    try:
        headers = {}
        token = st.session_state.get("token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = requests.post(BACKEND_UPLOAD_URL, files=files, headers=headers, timeout=60)
    except requests.exceptions.ConnectionError:
        st.error("Could not connect to Upload Service")
        return False

    if response.status_code == 401:
        st.error("Session expired. Please log in again.")
        logout()
        return False

    if response.status_code != 200:
        st.error(f"Upload failed: {response.text}")
        return False

    data = response.json()
    file_id = data.get("file_id", uploaded_file.name)

    if file_id not in st.session_state.uploaded_docs:
        st.session_state.uploaded_docs.append(file_id)

    current_selected = get_current_selected_docs()
    if file_id not in current_selected:
        current_selected.append(file_id)
        set_current_selected_docs(current_selected)

    widget_key = f"selected_docs_{st.session_state.current_session_id}"
    st.session_state[widget_key] = list(current_selected)

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

    return True


def query_retrieval_service(query: str, selected_docs: list[str]):
    payload = {"query": query, "selected_docs": selected_docs}
    try:
        headers = {}
        token = st.session_state.get("token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = requests.post(BACKEND_CHAT_URL, json=payload, headers=headers, timeout=60)
    except requests.exceptions.ConnectionError:
        return "Could not connect to Retrieval Service"

    if response.status_code == 401:
        return "Session expired. Please log in again."

    if response.status_code != 200:
        return f"Error: {response.text}"

    data = response.json()
    return data.get("answer", "")


def save_chat_to_backend():
    if not st.session_state.username:
        return
    documents = [
        {
            "file_id": event.get("file_id", ""),
            "filename": event.get("filename", event.get("file_id", "")),
            "uploaded_at": event.get("uploaded_at", ""),
        }
        for event in st.session_state.upload_events
    ]
    request_user_service(
        "PUT",
        "/state",
        data={
            "username": st.session_state.username,
            "chat_sessions": st.session_state.chat_sessions,
            "documents": documents,
        },
        timeout=8,
    )


if not st.session_state.logged_in:
    palette = THEME_PALETTES[get_theme_mode()]
    inject_password_strength_js()
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
        with st.form("signup_form"):
            new_username = st.text_input("Choose Username", key="signup_user")
            new_password = st.text_input(
                "Choose Password", type="password", key="signup_pass")
            if st.form_submit_button("Create Account", use_container_width=True):
                register_user(new_username, new_password)

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
                title = get_chat_display_title(session)
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
            type=["txt", "md", "pdf"],
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
            widget_key = f"selected_docs_{st.session_state.current_session_id}"
            if widget_key not in st.session_state:
                st.session_state[widget_key] = get_current_selected_docs()
            selected_docs = st.multiselect(
                "Select sources for this chat:",
                st.session_state.uploaded_docs,
                key=widget_key,
                format_func=get_doc_display_name,
            )
            set_current_selected_docs(selected_docs)
        else:
            st.caption("Upload a document first")

        st.divider()
        if st.button("Log out", use_container_width=True):
            logout()

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
            update_current_chat_title(prompt)
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
