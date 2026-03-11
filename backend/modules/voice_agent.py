import asyncio
import json
import traceback
from typing import AsyncGenerator
from vertexai.generative_models import GenerativeModel, Part
from modules.tts_engine import generate_warning_audio

model = GenerativeModel("gemini-2.5-flash")

async def stream_voice_chat(
    audio_bytes: bytes,
    context: dict,
    history: list,
    interrupt_event: asyncio.Event
) -> AsyncGenerator[dict, None]:
    """
    Streams a conversational response back from Gemini using the provided audio chunk.
    Yields text and audio data back to the websocket.
    """
    # Build a simple history string
    history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history[-10:]])
    
    prompt = (
        f"You are TrustKit, a senior real estate fraud investigator. "
        f"You are actively analyzing a property with a client to ensure they aren't being scammed. "
        f"Your tone is professional, grounded, and helpful—like a trusted expert advisor. "
        f"You are polite and conversational, but never overly bubbly or robotic. "
        f"CRITICAL INSTRUCTIONS FOR VOICE OUTPUT: "
        f"1. Speak in short, concise, and natural sentences. "
        f"2. Use periods and commas to create a natural speaking pace. Do not use exclamation points. "
        f"3. NEVER use bullet points, numbered lists, markdown formatting, or emojis. You are generating spoken dialogue, not a written report. "
        f"4. Give direct, insightful answers based on the scan context, without repeating the user's question.\n\n"
        f"Context from the scan report: {json.dumps(context)}\n\n"
        f"Recent Chat History:\n{history_str}"
    )
    
    # Send the raw audio webm blob to Gemini natively
    audio_part = Part.from_data(data=audio_bytes, mime_type="audio/webm")
    
    try:
        response_stream = await model.generate_content_async(
            [prompt, audio_part],
            stream=True
        )
        
        sentence_buffer = ""
        async for chunk in response_stream:
            if interrupt_event.is_set():
                print("[voice_agent] 🛑 Generation interrupted by user.")
                break
                
            text = getattr(chunk, "text", "")
            if not text:
                continue
                
            # Yield text chunks immediately so the UI chat log updates live
            yield {"type": "chat_reply", "message": text}
            
            sentence_buffer += text
            
            # Simple chunking for TTS: Wait for punctuation to submit to TTS engine
            if any(punc in sentence_buffer for punc in ['.', '!', '?', '\n']):
                clean_sentence = sentence_buffer.strip()
                if clean_sentence:
                    audio_b64 = await asyncio.to_thread(generate_warning_audio, clean_sentence)
                    if audio_b64 and not interrupt_event.is_set():
                        yield {"type": "chat_reply", "audio_data": audio_b64}
                sentence_buffer = ""
                
        # Send any remaining text to TTS
        clean_sentence = sentence_buffer.strip()
        if clean_sentence and not interrupt_event.is_set():
            audio_b64 = await asyncio.to_thread(generate_warning_audio, clean_sentence)
            if audio_b64:
                yield {"type": "chat_reply", "audio_data": audio_b64}
                
    except Exception as e:
        print(f"[voice_agent] Streaming error: {e}")
        traceback.print_exc()
        yield {"type": "chat_reply", "message": " (Audio connection lost...)" }
