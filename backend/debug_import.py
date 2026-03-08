import traceback

try:
    from google.cloud import texttospeech
    print("SUCCESS")
except Exception as e:
    print("FAILED")
    traceback.print_exc()
