# Shikigen

An AI agent chat assistant — users converse with an AI agent that processes messages, calls tools, and streams responses.

## Language

**Agent**:
An AI-powered autonomous entity that processes user messages, reasons, and may invoke tools to generate responses.
_Avoid_: Bot, LLM, model (these describe components, not the entity the user interacts with)

**Conversation**:
A sequence of messages exchanged between a user and the agent, bounded by a session.
_Avoid_: Chat, thread, dialogue

**Message**:
A single exchange within a conversation — either from the user (a prompt) or from the agent (a response).
_Avoid_: Prompt, reply, utterance
