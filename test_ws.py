import asyncio
import websockets
import json

async def test_ws():
    uri = 'ws://localhost:8000/ws/live'
    async with websockets.connect(uri) as websocket:
        # First send a test chat message
        print("Sending chat message...")
        await websocket.send(json.dumps({'text': 'What is the trust score of the house?'}))
        
        # Then wait for the response
        print("Waiting for response...")
        response = await websocket.recv()
        data = json.loads(response)
        
        print('RESPONSE TYPE:', data.get('type'))
        print('RESPONSE MESSAGE:', data.get('message'))
        print('AUDIO DATA LOCATED?', 'audio_data' in data and len(data.get('audio_data', '')) > 50)
        
if __name__ == "__main__":
    asyncio.run(test_ws())
