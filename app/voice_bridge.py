import asyncio
import base64
import json
import os
from pathlib import Path
from typing import AsyncIterable
import audioop
import logging

from dotenv import load_dotenv
from quart import Quart, request, websocket
from quart.helpers import make_response
from google import genai
from google.genai import types
from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from google.adk.events.event import Event
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService

# Import your voice-optimized agent
from jarvis.voice_agent import voice_agent

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_NAME = "Jarvis Voice Assistant"
session_service = InMemorySessionService()

app = Quart(__name__)

class JarvisVoiceBridge:
    def __init__(self):
        # Initialize Gemini client
        self.client = genai.Client(vertexai=True, 
                                 project=os.getenv('GOOGLE_CLOUD_PROJECT'), 
                                 location='us-central1')
        
        # Gemini Live API configuration for voice
        self.model_id = "gemini-2.0-flash-exp"
        self.config = {
            "response_modalities": ["AUDIO"],
            "speech_config": types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede"  # Choose a pleasant voice
                    )
                )
            )
        }
        
        # ADK Runner setup
        self.runner = Runner(
            app_name=APP_NAME,
            agent=voice_agent,
            session_service=session_service,
        )
        
        # Track active streams
        self.stream_sid = None
        self.session_id = None

    async def start_agent_session(self, call_sid):
        """Initialize ADK agent session for this call"""
        try:
            session = await session_service.create_session(
                app_name=APP_NAME,
                user_id=f"caller_{call_sid}",
                session_id=call_sid,
            )
            self.session_id = session.id
            logger.info(f"Created ADK session: {self.session_id}")
            return session
        except Exception as e:
            logger.error(f"Failed to create ADK session: {e}")
            raise

    async def twilio_audio_stream(self):
        """Handle incoming Twilio media stream and convert audio format"""
        while True:
            try:
                message = await websocket.receive()
                data = json.loads(message)
                
                if data['event'] == 'start':
                    self.stream_sid = data['start']['streamSid']
                    call_sid = data['start'].get('callSid', 'unknown')
                    logger.info(f"📞 Call started - StreamSID: {self.stream_sid}, CallSID: {call_sid}")
                    
                    # Initialize ADK session for this call
                    await self.start_agent_session(call_sid)
                    
                elif data['event'] == 'media':
                    # Extract and convert audio from Twilio format
                    audio_data = data['media']['payload']  # Base64 encoded μ-law
                    decoded_audio = base64.b64decode(audio_data)
                    # Convert μ-law to 16-bit PCM
                    pcm_audio = audioop.ulaw2lin(decoded_audio, 2)
                    yield pcm_audio
                    
                elif data['event'] == 'stop':
                    logger.info("📞 Call ended")
                    break
                    
            except Exception as e:
                logger.error(f"Error processing Twilio stream: {e}")
                break

    def convert_audio_to_mulaw(self, audio_data: bytes) -> str:
        """Convert PCM audio to μ-law format for Twilio"""
        try:
            # Convert sample rate from 24kHz to 8kHz for phone quality
            converted_audio, _ = audioop.ratecv(audio_data, 2, 1, 24000, 8000, None)
            # Convert to μ-law
            mulaw_audio = audioop.lin2ulaw(converted_audio, 2)
            # Encode as base64
            return base64.b64encode(mulaw_audio).decode('utf-8')
        except Exception as e:
            logger.error(f"Audio conversion error: {e}")
            return ""

    async def process_with_adk_agent(self, text_input: str):
        """Process text through ADK agent and return response"""
        try:
            if not self.session_id:
                logger.error("No active ADK session")
                return "I'm sorry, there seems to be a technical issue."

            # Create content for ADK agent
            content = types.Content(
                role='user', 
                parts=[types.Part(text=text_input)]
            )
            
            # Run through ADK agent
            events_async = self.runner.run_async(
                session_id=self.session_id,
                user_id=f"caller_{self.stream_sid}",
                new_message=content
            )
            
            # Collect agent response
            response_text = ""
            async for event in events_async:
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            response_text += part.text
            
            return response_text if response_text else "I understand, but I'm not sure how to help with that."
            
        except Exception as e:
            logger.error(f"ADK agent processing error: {e}")
            return "I'm sorry, I encountered an error processing your request."

    async def handle_voice_call(self):
        """Main handler for voice calls - integrates Gemini Live with ADK agent"""
        try:
            logger.info("🎤 Establishing Gemini Live connection...")
            
            async with self.client.aio.live.connect(
                model=self.model_id, 
                config=self.config
            ) as session:
                
                logger.info("✅ Connected to Gemini Live API")
                
                # Start streaming audio from Twilio to Gemini
                async for response in session.start_stream(
                    stream=self.twilio_audio_stream(), 
                    mime_type='audio/pcm'
                ):
                    try:
                        # Handle different types of responses from Gemini
                        if response.data:
                            # Audio response from Gemini - send back to Twilio
                            audio_payload = self.convert_audio_to_mulaw(response.data)
                            if audio_payload:
                                message = {
                                    "event": "media",
                                    "streamSid": self.stream_sid,
                                    "media": {"payload": audio_payload}
                                }
                                await websocket.send(json.dumps(message))
                                logger.info("🔊 Sent audio response to caller")
                        
                        elif response.text:
                            # Text response - convert to speech via Gemini and send
                            # (This handles cases where Gemini returns text instead of audio)
                            logger.info(f"📝 Processing text through ADK: {response.text}")
                            
                            # Process through your ADK agent for enhanced responses
                            enhanced_response = await self.process_with_adk_agent(response.text)
                            
                            # Send enhanced response back to Gemini for speech synthesis
                            await session.send_message(enhanced_response)
                            
                    except Exception as e:
                        logger.error(f"Error processing Gemini response: {e}")
                        
        except Exception as e:
            logger.error(f"Voice call handler error: {e}")
            # Send error message to caller
            error_message = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": base64.b64encode(b"Sorry, I encountered a technical issue.").decode()}
            }
            await websocket.send(json.dumps(error_message))

# Quart app routes
@app.route('/twiml', methods=['POST'])
async def handle_incoming_call():
    """TwiML endpoint for incoming calls"""
    logger.info("📞 Incoming call received")
    
    # Get the base URL for WebSocket connection
    base_url = request.url_root.replace('http', 'ws').rstrip('/')
    websocket_url = f"{base_url}/voice"
    
    # TwiML response to connect call to WebSocket
    twiml_response = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Hello! Connecting you to Jarvis, your AI assistant.</Say>
    <Connect>
        <Stream url="{websocket_url}" />
    </Connect>
</Response>'''
    
    response = await make_response(twiml_response)
    response.headers['Content-Type'] = 'application/xml'
    return response

@app.websocket('/voice')
async def voice_websocket():
    """WebSocket endpoint for Twilio media streams"""
    logger.info("🔌 WebSocket connection established")
    bridge = JarvisVoiceBridge()
    try:
        await bridge.handle_voice_call()
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        logger.info("🔌 WebSocket connection closed")

@app.route('/health')
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Jarvis Voice Bridge"}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True) 