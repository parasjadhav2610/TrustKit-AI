import sys
from modules.tts_engine import generate_chat_response

print("Running test...")
try:
    generate_chat_response("Hi there, does this property look good?", {})
    print("Done generating chat response.")
except Exception as e:
    import traceback
    traceback.print_exc()
