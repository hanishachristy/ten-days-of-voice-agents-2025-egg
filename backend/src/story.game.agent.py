import os
import logging
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from dotenv import load_dotenv

# LiveKit Agent imports
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
# LiveKit Plugin imports
from livekit.plugins import google, murf, deepgram, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv(".env.local")
# Renamed logger for the new theme
logger = logging.getLogger("true.crime.investigation.agent")

# --- Configuration for Saving Case Files ---
# Renamed directory and variable for the theme
CASE_FILE_DIR = Path(__file__).parent.joinpath('case_files')
CASE_FILE_DIR.mkdir(exist_ok=True) # Ensure the directory exists

# --- Detective Agent Logic Class (Updated for Case Files) ---

class DetectiveLogic:
    """
    Manages the Detective Agent's state, including the feature to save case history.
    The agent acts as the facilitator for the player's investigation.
    """
    def __init__(self):
        logger.info("Detective Logic initialized for the Andie Bell Cold Case. Case file directory: %s", CASE_FILE_DIR)

    def _get_player_info(self, chat_history: List[Dict[str, Any]]) -> str:
        """Attempts to extract the player's name/persona, defaulting to the protagonist."""
        for msg in chat_history:
            if msg.get('role') == 'user':
                content = msg.get('content', '').lower()
                if 'pip' in content or 'pippa' in content:
                    return "Pip_Fitz-Amobi"
                
                # Check for other name suggestions
                if 'my name is' in content:
                    name_part = content.split('my name is', 1)[1].split(',')[0].strip()
                    return name_part.title()
                
        return "Pip_Fitz-Amobi" # Default name for A Good Girl's Guide to Murder

    def save_case_state(self, chat_history: List[Dict[str, Any]]) -> str:
        """Accesses the full chat history and saves it to a JSON case file."""
        if not chat_history:
            return "❌ Cannot save: The case history is empty."

        player_name = self._get_player_info(chat_history)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Updated game name
        save_data = {
            "case": "Andie Bell Cold Case",
            "investigator": player_name,
            "save_time": timestamp,
            "turns_count": len(chat_history),
            "investigation_log": chat_history
        }

        filename = CASE_FILE_DIR.joinpath(f"{player_name}_Case_{timestamp}.json")
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=4)
            logger.info("Case file saved to: %s", filename)
            return f"✅ Case File logged successfully as {filename.name}."
        except Exception as e:
            logger.error("Error saving case file: %s", e)
            return f"❌ Error saving case file: {e}"

    def start_new_investigation(self) -> str:
        """The command to trigger the next session (after saving)."""
        return "New case file opened. The red string board is blank. Welcome back to the investigation."


# --- Initialize Logic Instance and Tool Function ---

DETECTIVE_LOGIC = DetectiveLogic()

@function_tool
async def start_new_investigation_tool(ctx: RunContext) -> str: 
    """
    Triggers the save sequence by accessing the current chat history, 
    and then signals the LLM to start a new investigation.
    """
    
    # Ensure compatibility with different history formats if needed
    if hasattr(ctx, 'history') and ctx.history:
        try:
            # Convert LiveKit history objects to a simple list of dicts
            chat_history = [{'role': m.role, 'content': m.content} for m in ctx.history]
        except AttributeError:
            chat_history = ctx.history

        # Save the current case file
        save_message = await asyncio.to_thread(DETECTIVE_LOGIC.save_case_state, chat_history)
        
        # The tool returns the save message and the restart signal.
        return save_message + " " + DETECTIVE_LOGIC.start_new_investigation()
    
    return "Could not save previous case file. " + DETECTIVE_LOGIC.start_new_investigation()


# --- The LiveKit Detective Class (The Persona) ---

class Detective(Agent):
    def __init__(self) -> None:
        super().__init__(
            # Updated instructions for A Good Girl's Guide to Murder theme
            instructions="""You are the **Detective Agent** for an interactive, single-player, voice-only investigation game based on the **Andie Bell Cold Case** from *A Good Girl's Guide to Murder*. Your role is to guide the player (who is acting as **Pip Fitz-Amobi**, the lead investigator) through the case, presenting suspects, clues, and leads.

            **Universe & Tone:** You narrate a modern true-crime investigation setting (Fairview High/Little Kilton). The tone is focused, analytical, and slightly suspicious. The goal is to uncover the true killer, clearing the name of Sal Singh.

            **Goal and Initial Setup (STRICTLY FOLLOW THIS FLOW):**
            1. **First Turn:** You MUST immediately narrate the opening scene: Pip's small study, the red string investigation board, the *initial facts* of the case (Andie disappeared 5 years ago, Sal Singh convicted), and the first key pieces of evidence. **Do NOT ask for the player's name.**
            2. **The Investigation:** The core puzzle is finding and interviewing witnesses and cross-referencing their statements to find the inconsistencies that lead to the real killer.
            
            **Core Rule: Quadruple Choice (STRICTLY ENFORCED):**
            * Every single decision presented to the player **MUST** offer exactly **FOUR** distinct, labeled options: **(A), (B), (C), and (D).** These options must be investigative actions (e.g., Interview a suspect, Examine a piece of evidence, Re-read an old report).
            * The story must be designed to last between **8 and 10 exchanges** total, leading to the identification of the real culprit or a major dead end.
            
            **Continuity:** You must perfectly remember the player's past actions, witness statements, and the state of the evidence.

            **Action Prompt:** You **MUST** end every turn by presenting the four investigative options and asking: "**Which action (A, B, C, or D) do you choose for the investigation?**"
            
            **Special Command:** When the player asks to restart, they will trigger your `start_new_investigation_tool`. After the tool provides its output, you MUST reset the scene entirely by narrating the initial room description and case setup again.

            **Your First Turn: Begin the Cold Case Investigation now!**
            **Detective Agent:** You are **Pip Fitz-Amobi**, a determined student starting her Capstone project—investigating the murder of **Andie Bell** and the apparent suicide of her boyfriend, **Sal Singh**, five years ago. You sit in your study, surrounded by red string and photos. The official story is a closed case, but you’re certain Sal was innocent. Your evidence board is ready, displaying the first two facts: **Andie's phone was found** but was wiped clean, and **Sal had no history of violence**.

            * **(A)** Re-examine the police report logs for all calls made the week Andie disappeared.
            * **(B)** Track down and interview **Ravi Singh**, Sal's brother, for new insight.
            * **(C)** Focus on the 'missing 60 minutes' in Sal's alibi before his apparent crime.
            * **(D)** Scrutinize the social media profile of **Max Hastings**, a key witness with a known temper.

            **Which action (A, B, C, or D) do you choose for the investigation?**
            """,
            tools=[start_new_investigation_tool] # Tool updated with the new name
        )

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    # Initialize the LLM, STT, and TTS components
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash", api_key=os.getenv("GOOGLE_API_KEY")),
        # Updated TTS style to be appropriate for a crime documentary/podcast narrator
        tts=murf.TTS(voice="en-US-matthew", style="Documentary", text_pacing=True), 
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    await session.start(
        agent=Detective(), # Class name updated
        room=ctx.room,
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
