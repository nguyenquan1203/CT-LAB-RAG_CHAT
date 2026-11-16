import time

import streamlit as st

from config import FIREBASE_API_KEY, GUIDE_PATH, OLLAMA_BASE_URL
from firebase_client import FirebaseError, create_account, sign_in
from rag import RAGError, build_index, generate, retrieve, strip_thinking


def forget_user():
    # User details and chat history belong only to this session.
    st.session_state.clear()


@st.cache_resource(show_spinner=False)
def cached_index(base_url, guide_json):
    # Cache only the public guide and vectors, never accounts or chat history.
    return build_index(guide_json, base_url)


def show_sources(hits):
    with st.expander("Retrieved entries and similarity scores"):
        for hit in hits:
            st.markdown(f"**[{hit['id']}] {hit['title']}**")
            st.caption(f"Cosine similarity: {hit['score']:.4f}")
            st.write(hit["text"])
            st.markdown(f"[Reference source]({hit['source']})")


def main():
    st.set_page_config(page_title="Ho Chi Minh City Travel Guide", layout="centered")
    st.title("Ho Chi Minh City Travel Guide")
    st.caption("Ask about places, food and seasons. Answers cite entries from the travel guide.")

    user = st.session_state.get("user")
    if user and time.time() >= user.get("expires_at", 0):
        forget_user()
        st.session_state["notice"] = "Your session has expired. Please sign in again."
        user = None
    if notice := st.session_state.pop("notice", None):
        st.info(notice)

    if not user:
        st.subheader("Sign in to chat")
        if not FIREBASE_API_KEY:
            st.info("Set FIREBASE_API_KEY in .env, then restart the app.")
            st.stop()
        with st.form("account_form", clear_on_submit=True):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            login = st.form_submit_button("Sign in")
            register = st.form_submit_button("Sign up")
        try:
            if register:
                create_account(email, password)
                st.success("Account created. You can now sign in.")
            elif login:
                authenticated = sign_in(email, password)
                forget_user()
                st.session_state["user"] = authenticated
                st.rerun()
        except FirebaseError as error:
            st.error(str(error))
        st.stop()

    with st.sidebar:
        st.write(f"Signed in as: {user['email']}")
        st.button("Sign out", on_click=forget_user)
        st.divider()
        st.caption("Example questions")
        st.write("Where is the Saigon Central Post Office?")
        st.write("Which months are usually the dry season in Ho Chi Minh City?")
        st.write("How much is admission to the War Remnants Museum?")

    st.session_state.setdefault("messages", [])
    for message in st.session_state["messages"]:
        if message["role"] == "assistant":
            message["content"] = strip_thinking(message["content"])
        with st.chat_message(message["role"]):
            st.write(message["content"] or "No final answer was returned. Please ask again.")
            if "hits" in message:
                show_sources(message["hits"])
    if not st.session_state["messages"]:
        st.info("The guide contains 12 entries. The assistant will say it does not know when information is missing.")
    question = st.chat_input("Ask a question about Ho Chi Minh City", max_chars=2000)
    if question is None:
        return
    if not question.strip():
        st.warning("Please enter a question.")
        return
    try:
        with st.spinner("Looking for information in the travel guide..."):
            guide_json = GUIDE_PATH.read_text(encoding="utf-8")
            records, vectors = cached_index(OLLAMA_BASE_URL, guide_json)
            hits = retrieve(question, records, vectors, OLLAMA_BASE_URL)
            answer = generate(question, hits, OLLAMA_BASE_URL)
        st.session_state["messages"].extend([
            {"role": "user", "content": question.strip()},
            {"role": "assistant", "content": answer, "hits": hits},
        ])
        st.rerun()
    except OSError:
        st.error("Cannot read the guide. Check that knowledge_base.json is next to app.py.")
    except RAGError as error:
        st.error(str(error))


if __name__ == "__main__":
    main()

