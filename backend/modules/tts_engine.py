"""TrustKit AI — Text-to-Speech Engine Module.

Converts AI agent analysis results into natural spoken language so the user can hear
alerts and warnings during a live tour without looking at the screen.

Handles:
1. Converting structured risk reports into natural language.
2. Converting text to speech.
3. Returning audio bytes to the frontend.

Libraries:
- google-cloud-texttospeech (Primary)
- gTTS (Fallback MVP)
"""

import base64
import json
import os
from io import BytesIO

def _generate_natural_language(report: dict) -> str:
    """Converts a structured risk report into a natural language string.
    
    Args:
        report (dict): The assessment from the agent reasoner containing 
                       'alert', 'message', and 'trust_score'.
                       
    Returns:
        str: A short, conversational, empathetic spoken warning string.
    """
    if not report.get("alert"):
        return "Everything looks good so far. No issues detected."
        
    base_message = report.get("message", "I have detected some potential issues with the property.")
    score = report.get("trust_score", 50)
    
    # Try using Gemini to generate a conversational, empathetic warning
    try:
        from modules.agent_reasoner import _get_model
        model = _get_model()
        
        if model:
            prompt = (
                f"You are TrustKit AI, an empathetic, conversational real-estate AI copilot "
                f"on a live video call with a user. You've just detected a warning: '{base_message}'. "
                f"The overall trust score is {score} out of 100. "
                f"Generate a very short, natural spoken warning (under 15 words) for the user. "
                f"Use a conversational and helpful tone, not robotic. Do not use quotes or formatting. "
                f"Just return the exact text to speak."
            )
            response = model.generate_content(prompt)
            return response.text.strip()
            
    except Exception as e:
        print(f"[tts_engine] Gemini text generation failed: {e}. Falling back to default.")

    # Fallback to simple templates if Gemini fails or is missing
    if score < 40:
        return f"Warning. The trust score is very low at {score}. {base_message}"
    elif score < 80:
        return f"Caution. I found some warnings. {base_message}"
    else:
        return base_message

def generate_chat_response(transcription: str, context: dict = None) -> str:
    """Generates a conversational response to a user's question during post-call chat.
    
    Args:
        transcription (str): The user's spoken or typed input.
        context (dict, optional): The previous risk report or forensic context to answer from.
        
    Returns:
        str: A conversational textual response from the agent.
    """
    try:
        from modules.agent_reasoner import _get_model
        model = _get_model()
        
        if model:
            context_str = json.dumps(context) if context else "No active report context."
            prompt = (
                f"You are TrustKit AI, an empathetic, helpful real-estate AI copilot answering "
                f"a user's questions after a property tour.\n\n"
                f"Context from the scan: {context_str}\n\n"
                f"User says: '{transcription}'\n\n"
                f"Give a helpful, conversational, and direct answer. Be brief and natural to speak. "
                f"Do not use markdown, emojis, or bullet points. Just return the exact text to speak."
            )
            response = model.generate_content(prompt)
            return response.text.strip()
    except Exception as e:
        print(f"[tts_engine] Gemini chat response failed: {e}.")
        
    return "I'm having trouble connecting to my brain right now, but I heard you say: " + transcription

def generate_warning_audio(text_or_report) -> str:
    """Convert a warning text or risk report dict into audio output.

    Args:
        text_or_report (str | dict): Either a direct text string to speak,
                                     or a dict risk report from agent_reasoner.

    Returns:
        A Data URI string representing the audio output.
        Format: "data:audio/mp3;base64,..."
    """
    if isinstance(text_or_report, dict):
        text_to_speak = _generate_natural_language(text_or_report)
    else:
        text_to_speak = str(text_or_report)
        
    if not text_to_speak:
        return ""

    # Attempt Option 2: Google Cloud TTS (if credentials exist)
    try:
        from google.cloud import texttospeech
        
        # This requires GOOGLE_APPLICATION_CREDENTIALS to be set in the environment
        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text_to_speak)
        
        # Build the voice request, select the language code and the ssml voice gender
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name="en-US-Journey-F", # A professional conversational voice
        )
        
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=0.95,
            pitch=-2.0
        )
        
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        
        base64_audio = base64.b64encode(response.audio_content).decode('utf-8')
        return f"data:audio/mp3;base64,{base64_audio}"
        
    except Exception as e:
        print(f"[tts_engine] Google Cloud TTS failed or unavailable: {e}. Falling back to gTTS MVP.")
        
        # Fallback Option 1: gTTS (MVP)
        try:
            from gtts import gTTS
            import tempfile
            
            tts = gTTS(text=text_to_speak, lang="en", slow=False)
            
            # Use a temporary file since `write_to_fp` can fail on Windows
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fp:
                temp_filename = fp.name
                
            tts.save(temp_filename)
            
            with open(temp_filename, "rb") as f:
                audio_bytes = f.read()
                
            os.remove(temp_filename)
            
            base64_audio = base64.b64encode(audio_bytes).decode('utf-8')
            
            return f"data:audio/mp3;base64,{base64_audio}"
        except Exception as e2:
            print(f"[tts_engine] gTTS fallback failed: {e2}")
            return "Warning: The view does not match the listing description."
