import os
from dotenv import load_dotenv
load_dotenv()

from modules.tts_engine import generate_warning_audio

report = {
    'alert': True, 
    'message': 'I found a suspicious reflection in the mirror.', 
    'trust_score': 30
}

print("Testing Google Cloud Authentication...")
try:
    from google.cloud import texttospeech
    client = texttospeech.TextToSpeechClient()
    print("Google Cloud Auth Success!")
    
    print("Generating audio...")
    audio_data = generate_warning_audio(report)
    
    print("Writing to test_audio.html...")
    with open("test_audio.html", "w") as f:
        f.write(f'<html><body><h1>TTS Test</h1><audio controls src="{audio_data}"></audio></body></html>')
    
    print("Done! You can open test_audio.html in your browser to hear the result.")

except Exception as e:
    import traceback
    print(f"FAILED TO AUTHENTICATE GOOGLE CLOUD:")
    traceback.print_exc()
