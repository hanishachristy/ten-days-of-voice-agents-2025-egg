# backend/src/agent.py
import os
import json
import logging
import asyncio
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

from dotenv import load_dotenv
load_dotenv(".env.local")

# standard fuzzy matching helper
import difflib

logger = logging.getLogger("story.agent")
logger.setLevel(logging.INFO)

# --- LiveKit Agent imports (same as your original) ---
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    function_tool,
    RunContext,
)
# LiveKit Plugin imports (same as original)
from livekit.plugins import google, murf, deepgram, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

# --- Story file path (relative to this file's parent parent dir) ---
STORY_PATH = Path(__file__).parent.parent.joinpath("story.json")
if not STORY_PATH.exists():
    logger.error(f"story.json not found at {STORY_PATH}. Please place story.json there.")
    # Do not raise here so that the worker can start; tools will error gracefully if story not loaded.

# --- Load story.json into memory ---
def load_story() -> Dict[str, Any]:
    try:
        with open(STORY_PATH, "r", encoding="utf-8") as f:
            story = json.load(f)
            # Ensure scenes is a dict
            scenes = story.get("scenes", {})
            return {"meta": {k: story.get(k) for k in ("title", "start_scene")}, "scenes": scenes}
    except FileNotFoundError:
        logger.exception("story.json not found.")
        return {"meta": {}, "scenes": {}}
    except json.JSONDecodeError:
        logger.exception("Invalid JSON in story.json.")
        return {"meta": {}, "scenes": {}}

STORY_DATA = load_story()

# --- Simple in-memory session store ---
# session_id -> { "current_scene": str, "created_at": iso, "history": [ {scene, choice_label, choice_id, at} ] }
SESSIONS: Dict[str, Dict[str, Any]] = {}

def new_session(start_scene_override: Optional[str] = None) -> str:
    sid = str(uuid.uuid4())
    start_scene = start_scene_override or STORY_DATA["meta"].get("start_scene")
    if not start_scene:
        # fallback: pick first scene key if available
        scenes_keys = list(STORY_DATA["scenes"].keys())
        start_scene = scenes_keys[0] if scenes_keys else None
    SESSIONS[sid] = {
        "current_scene": start_scene,
        "created_at": datetime.utcnow().isoformat(),
        "history": []
    }
    logger.info(f"Created new session {sid} with start_scene={start_scene}")
    return sid

def get_session(sid: str) -> Optional[Dict[str, Any]]:
    return SESSIONS.get(sid)

def set_scene_for_session(sid: str, scene_id: Optional[str]):
    if sid in SESSIONS:
        SESSIONS[sid]["current_scene"] = scene_id

# --- Helpers for scene/choice lookup ---
def get_scene(scene_id: str) -> Optional[Dict[str, Any]]:
    return STORY_DATA["scenes"].get(scene_id)

def format_scene_output(scene: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize scene to a small payload suitable for TTS and agent responses.
    """
    if not scene:
        return {"id": None, "title": None, "narration": None, "lines": [], "choices": []}
    choices = scene.get("choices", [])
    # choices might be list of objects like {id, label, next_scene}
    formatted_choices = []
    for c in choices:
        # support both list-of-dicts and map-style if present
        if isinstance(c, dict):
            formatted_choices.append({"id": c.get("id"), "label": c.get("label"), "next_scene": c.get("next_scene")})
        else:
            # ignore unexpected shape
            continue
    return {
        "id": scene.get("id"),
        "title": scene.get("title"),
        "narration": scene.get("narration"),
        "lines": scene.get("lines", []),
        "choices": formatted_choices
    }

def _choice_labels_for_scene(scene: Dict[str, Any]) -> List[str]:
    formatted = format_scene_output(scene)
    return [c["label"] for c in formatted["choices"] if c.get("label")]

# --- Matching logic: map free-form user utterance to best choice ---
def map_user_input_to_choice(scene: Dict[str, Any], user_input: str, cutoff: float = 0.45) -> Optional[Dict[str, Any]]:
    """
    Attempt to map user_input (raw text) to one of the scene's choices.
    Uses difflib for fuzzy matching on choice labels and also attempts to match on
    choice ids or short keywords.
    Returns the matched choice dict or None.
    """
    if not scene:
        return None
    formatted = format_scene_output(scene)
    choices = formatted["choices"]
    if not choices:
        return None

    # Build list of candidate strings
    candidates = []
    label_to_choice = {}
    for c in choices:
        label = c.get("label", "").strip()
        cid = c.get("id")
        # Add label as candidate
        if label:
            candidates.append(label)
            label_to_choice[label] = c
        # Add id as a candidate if present
        if cid:
            candidates.append(str(cid))
            label_to_choice[str(cid)] = c

    # Lowercased matching
    user_lower = user_input.strip().lower()

    # Fast direct substring match (prefer exact)
    for lab, ch in label_to_choice.items():
        if lab.lower() in user_lower or user_lower in lab.lower():
            return ch

    # Use difflib to find closest label
    # difflib returns matches ordered by similarity
    close = difflib.get_close_matches(user_input, candidates, n=3, cutoff=cutoff)
    if close:
        best = close[0]
        return label_to_choice.get(best)

    # Token overlap fallback: compare set intersection ratio
    user_tokens = set([t for t in user_lower.split() if len(t) > 2])
    best_choice = None
    best_score = 0.0
    for lab in candidates:
        lab_tokens = set([t for t in lab.lower().split() if len(t) > 2])
        if not lab_tokens or not user_tokens:
            continue
        inter = user_tokens.intersection(lab_tokens)
        score = len(inter) / max(len(lab_tokens), 1)
        if score > best_score:
            best_score = score
            best_choice = label_to_choice.get(lab)
    if best_score >= 0.34:
        return best_choice

    # If nothing confident found, return None
    return None

# --- Async wrappers for story operations (to be used by tools) ---
async def async_get_scene_for_session(sid: str) -> Dict[str, Any]:
    session = get_session(sid)
    if not session:
        return {"error": "session_not_found"}
    scene_id = session.get("current_scene")
    if not scene_id:
        return {"error": "no_current_scene"}
    scene = await asyncio.to_thread(get_scene, scene_id)
    return {"scene": format_scene_output(scene)}

async def async_start_session(start_scene_override: Optional[str] = None) -> Dict[str, Any]:
    sid = await asyncio.to_thread(new_session, start_scene_override)
    # Immediately return the starting scene
    scene_payload = await async_get_scene_for_session(sid)
    return {"session_id": sid, **scene_payload}

async def async_choose_option(sid: str, user_input: str) -> Dict[str, Any]:
    session = get_session(sid)
    if not session:
        return {"error": "session_not_found", "message": "Session not found. Start a new game."}
    current_scene_id = session.get("current_scene")
    current_scene = await asyncio.to_thread(get_scene, current_scene_id)
    if not current_scene:
        return {"error": "scene_not_found", "message": "Current scene not found."}

    chosen = await asyncio.to_thread(map_user_input_to_choice, current_scene, user_input)
    if not chosen:
        # Did not confidently map — return clarification request and available choices
        available = _choice_labels_for_scene(current_scene)
        return {
            "error": "no_match",
            "message": "I didn't understand which option you meant. Please pick one of the available choices or repeat it more clearly.",
            "available_choices": available
        }

    # Apply choice: advance scene
    next_scene_id = chosen.get("next_scene")
    # Record history
    session["history"].append({
        "at": datetime.utcnow().isoformat(),
        "scene": current_scene_id,
        "choice_label": chosen.get("label"),
        "choice_id": chosen.get("id"),
        "next_scene": next_scene_id
    })
    # If next_scene_id is None -> end
    set_scene_for_session(sid, next_scene_id)
    next_scene = await asyncio.to_thread(get_scene, next_scene_id) if next_scene_id else None
    return {
        "applied_choice": {"id": chosen.get("id"), "label": chosen.get("label"), "next_scene": next_scene_id},
        "next_scene": format_scene_output(next_scene) if next_scene else None
    }

async def async_reset_session(sid: str) -> Dict[str, Any]:
    session = get_session(sid)
    if not session:
        return {"error": "session_not_found"}
    start_scene = STORY_DATA["meta"].get("start_scene")
    set_scene_for_session(sid, start_scene)
    return await async_get_scene_for_session(sid)

# --- Tools exposed to the LLM / runtime ---

@function_tool
async def start_game_tool(ctx: RunContext[None], start_scene_override: Optional[str] = None) -> Dict[str, Any]:
    """
    Start a new story session. Returns:
      { session_id: str, scene: {id,title,narration,lines,choices} }
    """
    return await async_start_session(start_scene_override)

@function_tool
async def get_scene_tool(ctx: RunContext[None], session_id: str) -> Dict[str, Any]:
    """
    Return the current scene payload for the given session_id.
    """
    return await async_get_scene_for_session(session_id)

@function_tool
async def choose_option_tool(ctx: RunContext[None], session_id: str, user_spoken_choice: str) -> Dict[str, Any]:
    """
    Map a free-form user utterance (user_spoken_choice) to the best scene choice and advance the session.
    Returns applied_choice + next_scene, or an error with available choices.
    """
    return await async_choose_option(session_id, user_spoken_choice)

@function_tool
async def reset_game_tool(ctx: RunContext[None], session_id: str) -> Dict[str, Any]:
    """
    Reset the session to the starting scene.
    """
    return await async_reset_session(session_id)

# --- Agent / Assistant definition ---
class StoryAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are the Story Game Master guiding a player through an interactive mystery.\n"
                "Always use the provided tools for story state: start_game_tool, get_scene_tool, choose_option_tool, reset_game_tool.\n"
                "When a player speaks a choice, map it to one of the displayed choices using choose_option_tool.\n"
                "If mapping fails, ask the player to repeat or read out the available choices.\n"
                "Keep responses concise and focused on guiding the player and reading scene narration and lines.\n"
                "Do NOT invent new scene IDs or change story.json."
            ),
            tools=[start_game_tool, get_scene_tool, choose_option_tool, reset_game_tool],
        )

# --- Prewarm and entrypoint (setup TTS/STT/LLM like your original) ---

def prewarm(proc: JobProcess):
    # load a VAD model once
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("Prewarmed VAD model.")

async def entrypoint(ctx: JobContext):
    """
    Creates the AgentSession and starts the StoryAssistant.
    This closely follows your original template but uses the story assistant.
    """
    # create the session with plugins configured (STT, LLM, TTS, turn detector, vad)
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash", api_key=os.getenv("GOOGLE_API_KEY")),
        tts=murf.TTS(voice="en-US-matthew", style="Conversation", text_pacing=True),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    # start session with the assistant
    await session.start(
        agent=StoryAssistant(),
        room=ctx.room,
    )

    # connect
    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
