import streamlit as st
import requests
import time

# --- Config & Backend URLs ---
st.set_page_config(page_title="RAG Workspace", page_icon="📚", layout="wide")
BACKEND_UPLOAD_URL = "http://localhost:8000/upload"
# We will build this backend later
BACKEND_CHAT_URL = "http://localhost:8000/chat"

# --- Initialize Session State (Memory) ---
# This keeps track of data without resetting every time you click a button
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "uploaded_docs" not in st.session_state:
    st.session_state.uploaded_docs = []  # List of uploaded file names

# Mock Database for testing auth (Will move to MongoDB later)
MOCK_USERS = {"admin": "password123", "testuser": "1234"}

# --- Helper Functions ---


def login(username, password):
    if username in MOCK_USERS and MOCK_USERS[username] == password:
        st.session_state.logged_in = True
        st.session_state.username = username
        st.rerun()
    else:
        st.error("Invalid username or password")


def logout():
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.chat_history = []
    st.rerun()


def upload_to_backend(uploaded_file):
    try:
        # Send file to your FastAPI Upload Service
        files = {"file": (uploaded_file.name,
                          uploaded_file.getvalue(), uploaded_file.type)}
        response = requests.post(BACKEND_UPLOAD_URL, files=files)

        if response.status_code == 200:
            st.session_state.uploaded_docs.append(uploaded_file.name)
            return True
        else:
            st.error(f"Backend Error: {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        st.error("Could not connect to Backend. Is FastAPI running?")
        return False


# --- UI: Authentication Page ---
if not st.session_state.logged_in:
    st.title("📚 RAG Workspace Login")

    tab1, tab2 = st.tabs(["Login", "Sign Up"])

    with tab1:
        log_user = st.text_input("Username", key="log_user")
        log_pass = st.text_input("Password", type="password", key="log_pass")
        if st.button("Login"):
            login(log_user, log_pass)

    with tab2:
        st.info("Sign up is mocked for now. Please use the Login tab with username: 'admin', password: 'password123'")

# --- UI: Main Application (NotebookLM Style) ---
else:
    # --- Sidebar: Knowledge Management ---
    with st.sidebar:
        st.title(f"Welcome, {st.session_state.username}!")
        if st.button("Logout"):
            logout()

        st.divider()
        st.header("📄 Knowledge Base")

        # 1. File Upload Section
        uploaded_file = st.file_uploader(
            "Upload a new document", type=["txt", "md"])
        if uploaded_file is not None:
            if st.button("Process Document"):
                with st.spinner("Uploading and ingesting..."):
                    if upload_to_backend(uploaded_file):
                        st.success(f"{uploaded_file.name} added!")

        st.divider()

        # 2. Document Selection (NotebookLM Style Grounding)
        st.subheader("Selected Sources")
        if not st.session_state.uploaded_docs:
            st.caption("No documents uploaded yet.")
            selected_docs = []
        else:
            # Multi-select lets the user choose which docs to ask questions about
            selected_docs = st.multiselect(
                "Choose documents to chat with:",
                st.session_state.uploaded_docs,
                default=st.session_state.uploaded_docs  # Select all by default
            )

    # --- Main Area: Chat Interface ---
    st.title("💬 Document Chat")

    if not selected_docs:
        st.warning(
            "👈 Please upload and select at least one document from the sidebar to start chatting.")
    else:
        st.caption(
            f"Currently grounding answers using: {', '.join(selected_docs)}")

        # Display Chat History
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        # Chat Input Area
        if prompt := st.chat_input("Ask a question about your documents..."):
            # 1. Add user message to UI
            st.session_state.chat_history.append(
                {"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # 2. Get AI Response (Simulated for now, until Retrieval service is built)
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                message_placeholder.markdown("🤔 Thinking...")

                # --- FUTURE BACKEND HOOK ---
                # This is where we will call your FastAPI Retrieval Service later:
                # payload = {"query": prompt, "selected_docs": selected_docs}
                # response = requests.post(BACKEND_CHAT_URL, json=payload)
                # ai_response = response.json()["answer"]

                # Mocking the AI delay
                time.sleep(1.5)
                ai_response = f"This is a mock answer for: '{prompt}'. \n\n*In the future, this will be retrieved from ChromaDB using {selected_docs}.*"

                message_placeholder.markdown(ai_response)

            # 3. Save AI message to history
            st.session_state.chat_history.append(
                {"role": "assistant", "content": ai_response})
