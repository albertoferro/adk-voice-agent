import asyncio
import base64
import json
import os
from pathlib import Path
from typing import AsyncIterable
import struct
import logging
import numpy as np
import soxr

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

# Audio conversion functions to replace audioop
def ulaw2lin(ulaw_data, width):
    """Convert μ-law encoded audio to linear PCM"""
    if width != 2:
        raise ValueError("Only 16-bit (width=2) is supported")
    
    result = bytearray()
    for byte in ulaw_data:
        # μ-law to linear conversion with proper range handling
        byte = byte ^ 0xFF  # Un-invert bits
        sign = byte & 0x80
        exponent = (byte >> 4) & 0x07
        mantissa = byte & 0x0F
        
        # Linear value calculation with range limiting
        if exponent == 0:
            linear = (mantissa << 4) + 8
        else:
            linear = ((mantissa + 16) << (exponent + 3)) - 132
        
        if sign:
            linear = -linear
        
        # Clamp to 16-bit signed integer range
        linear = max(-32768, min(32767, linear))
        
        # Pack as 16-bit signed integer
        result.extend(struct.pack('<h', linear))
    
    return bytes(result)

def lin2ulaw(linear_data, width):
    """Convert linear PCM to μ-law encoded audio"""
    if width != 2:
        raise ValueError("Only 16-bit (width=2) is supported")
    
    result = bytearray()
    for i in range(0, len(linear_data), 2):
        # Unpack 16-bit signed integer
        if i + 1 < len(linear_data):
            try:
                sample = struct.unpack('<h', linear_data[i:i+2])[0]
            except struct.error:
                sample = 0
        else:
            sample = 0
        
        # Convert to μ-law with proper range handling
        sign = 0x80 if sample < 0 else 0x00
        sample = abs(sample)
        
        # Clamp sample to prevent overflow
        sample = min(sample, 32635)  # Slightly less than 32767 for safety
        
        # Add bias and find exponent
        sample += 132
        exponent = 7
        for exp in range(8):
            if sample <= (0x1F << (exp + 3)) + 132:
                exponent = exp
                break
        
        # Calculate mantissa
        if exponent == 0:
            mantissa = (sample - 132) >> 4
        else:
            mantissa = ((sample - 132) >> (exponent + 3)) - 16
        
        mantissa = max(0, min(15, mantissa))  # Clamp mantissa to 4-bit range
        
        # Combine components
        ulaw = sign | (exponent << 4) | mantissa
        result.append(ulaw ^ 0xFF)  # Invert bits as per μ-law standard
    
    return bytes(result)

def ratecv(audio_data, width, nchannels, inrate, outrate, state):
    """Simple sample rate conversion"""
    if width != 2 or nchannels != 1:
        raise ValueError("Only 16-bit mono is supported")
    
    # Handle empty or invalid input
    if not audio_data or len(audio_data) < 2:
        return b'', None
    
    # Simple decimation/interpolation based on rate ratio
    ratio = inrate / outrate
    
    if abs(ratio - 3.0) < 0.1:  # 24000 to 8000 Hz (3:1 ratio)
        # Simple decimation - take every 3rd sample
        result = bytearray()
        for i in range(0, len(audio_data) - 1, 6):  # 6 bytes = 3 samples * 2 bytes each
            if i + 1 < len(audio_data):
                result.extend(audio_data[i:i+2])
        return bytes(result), None
    else:
        # For other ratios, just return original data
        # In production, use a proper resampling library
        return audio_data, None

def mulaw_to_gemini_pcm(mulaw_bytes: bytes) -> np.ndarray:
    """
    Convert Twilio μ-law audio to Gemini Live compatible PCM format.
    Based on solution from: https://github.com/openai/openai-agents-python/issues/304
    """
    # Use our custom μ-law to PCM conversion (Python 3.13 compatible)
    pcm_bytes = ulaw2lin(mulaw_bytes, 2)
    audio_np = np.frombuffer(pcm_bytes, dtype=np.int16)
    
    # Resample from 8kHz (Twilio) to 24kHz (Gemini Live requirement)
    audio_24k = soxr.resample(audio_np, 8000, 24000)
    
    # Convert to float32 range [-1.0, 1.0] as expected by Gemini Live
    return (audio_24k / 32768.0).astype(np.float32)

class JarvisVoiceBridge:
    def __init__(self):
        # Initialize Gemini client
        self.client = genai.Client(vertexai=True, 
                                 project=os.getenv('GOOGLE_CLOUD_PROJECT'), 
                                 location='us-central1')
        
        # Gemini Live API configuration for voice
        self.model_id = "gemini-2.0-flash-exp"
        
        # ADK Runner setup
        self.runner = Runner(
            app_name=APP_NAME,
            agent=voice_agent,
            session_service=session_service,
        )
        
        # Track active streams
        self.stream_sid = None
        self.session_id = None
        
        # Audio buffering for better turn detection
        self.audio_buffer = bytearray()
        self.buffer_size = 4800  # ~100ms at 24kHz (480 samples * 10 chunks)

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
                    # Convert μ-law to Gemini Live compatible format (24kHz float32)
                    pcm_float32 = mulaw_to_gemini_pcm(decoded_audio)
                    # Convert numpy float32 array to bytes for Gemini Live API
                    pcm_bytes = pcm_float32.tobytes()
                    
                    # Buffer audio chunks for better turn detection
                    self.audio_buffer.extend(pcm_bytes)
                    
                    # Send buffered audio when we have enough for better processing
                    if len(self.audio_buffer) >= self.buffer_size:
                        buffered_audio = bytes(self.audio_buffer)
                        self.audio_buffer.clear()
                        logger.info(f"🎤 Sending buffered audio to Gemini: {len(buffered_audio)} bytes (~100ms chunk)")
                        yield buffered_audio
                    # Note: Small final chunks on call end will be handled by 'stop' event
                    
                elif data['event'] == 'stop':
                    # Send any remaining buffered audio before ending
                    if len(self.audio_buffer) > 0:
                        final_audio = bytes(self.audio_buffer)
                        self.audio_buffer.clear()
                        logger.info(f"🎤 Sending final buffered audio: {len(final_audio)} bytes")
                        yield final_audio
                    
                    logger.info("📞 Call ended")
                    break
                    
            except Exception as e:
                logger.error(f"Error processing Twilio stream: {e}")
                break

    def convert_audio_to_mulaw(self, audio_data: bytes) -> str:
        """Convert PCM audio to μ-law format for Twilio"""
        try:
            # Convert sample rate from 24kHz to 8kHz for phone quality
            converted_audio, _ = ratecv(audio_data, 2, 1, 24000, 8000, None)
            # Convert to μ-law
            mulaw_audio = lin2ulaw(converted_audio, 2)
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
            
            # Configure session for real-time phone calls - use only valid LiveConnectConfig parameters
            live_config = {
                "response_modalities": ["AUDIO"],
                "speech_config": types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Aoede"
                        )
                    )
                ),
                "system_instruction": """You are Jarvis, a voice assistant for phone calls. 
                
                CRITICAL PHONE CALL BEHAVIOR:
                - Respond quickly and naturally to user speech
                - Don't wait for long pauses - respond as soon as you understand the request
                - Keep responses concise and conversational
                - If you hear the user speaking, wait for them to finish their immediate thought, then respond
                - Be proactive in asking follow-up questions
                
                You help with DealMaker authentication and investor information."""
            }
            
            logger.info(f"🔧 Connecting with config: {live_config}")
            
            async with self.client.aio.live.connect(
                model=self.model_id, 
                config=live_config
            ) as session:
                
                logger.info("✅ Connected to Gemini Live API")
                
                # Start streaming audio from Twilio to Gemini
                logger.info("🎵 Starting audio stream: Twilio → Gemini Live (24kHz float32)")
                logger.info("🔧 Using mime_type: audio/pcm")
                
                # Note: Gemini Live AsyncSession doesn't support send_message, 
                # it will respond based on audio input and system instructions
                
                response_count = 0
                audio_stream = self.twilio_audio_stream()
                logger.info("🎤 Audio stream generator created successfully")
                
                async for response in session.start_stream(
                    stream=audio_stream, 
                    mime_type='audio/pcm'  # Simplified mime_type
                ):
                    response_count += 1
                    logger.info(f"🔄 Response #{response_count} received from Gemini Live")
                    try:
                        # Debug: Log all response types to understand what Gemini is sending
                        logger.info(f"🔄 Received response from Gemini Live: type={type(response)}, data={hasattr(response, 'data')}, text={hasattr(response, 'text')}")
                        
                        # Handle different types of responses from Gemini
                        if hasattr(response, 'data') and response.data:
                            # Audio response from Gemini - send back to Twilio
                            logger.info(f"🎵 Processing audio response: {len(response.data)} bytes")
                            audio_payload = self.convert_audio_to_mulaw(response.data)
                            if audio_payload:
                                message = {
                                    "event": "media",
                                    "streamSid": self.stream_sid,
                                    "media": {"payload": audio_payload}
                                }
                                await websocket.send(json.dumps(message))
                                logger.info("🔊 Sent audio response to caller")
                            else:
                                logger.warning("⚠️ Failed to convert Gemini audio to μ-law")
                        
                        elif hasattr(response, 'text') and response.text:
                            # Text response - convert to speech via Gemini and send
                            # (This handles cases where Gemini returns text instead of audio)
                            logger.info(f"📝 Processing text through ADK: {response.text}")
                            
                            # Process through your ADK agent for enhanced responses
                            enhanced_response = await self.process_with_adk_agent(response.text)
                            
                            # Send enhanced response back to Gemini for speech synthesis
                        
                        else:
                            # Debug: Log unexpected response types
                            logger.warning(f"⚠️ Unexpected response format from Gemini Live: {response}")
                            # Try to introspect the response object
                            if hasattr(response, '__dict__'):
                                logger.info(f"🔍 Response attributes: {list(response.__dict__.keys())}")
                            else:
                                logger.info(f"🔍 Response dir: {[attr for attr in dir(response) if not attr.startswith('_')]}")
                            # Note: Don't send enhanced_response here as it might not be defined
                            
                    except Exception as e:
                        logger.error(f"Error processing Gemini response: {e}")
                        continue
                
                # If we exit the response loop, log why
                logger.warning("🚨 Exited Gemini Live response loop - this shouldn't happen during active call")
                        
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
@app.route('/twiml/', methods=['POST'])
async def handle_incoming_call():
    """TwiML endpoint for incoming calls"""
    logger.info("📞 Incoming call received")
    
    # Get the base URL for WebSocket connection - detect ngrok
    forwarded_host = request.headers.get('X-Forwarded-Host')
    original_host = request.headers.get('Host')
    
    if forwarded_host and 'ngrok' in forwarded_host:
        # Request comes through ngrok - use secure WebSocket
        websocket_url = f"wss://{forwarded_host}/voice"
        logger.info(f"🌐 Using ngrok WebSocket URL: {websocket_url}")
    elif original_host and 'ngrok' in original_host:
        # Alternative ngrok detection
        websocket_url = f"wss://{original_host}/voice"
        logger.info(f"🌐 Using ngrok WebSocket URL: {websocket_url}")
    else:
        # Local development fallback
        base_url = request.url_root.replace('http', 'ws').rstrip('/')
        websocket_url = f"{base_url}/voice"
        logger.info(f"🏠 Using local WebSocket URL: {websocket_url}")
    
    # TwiML response to connect call to WebSocket with improved voice
    twiml_response = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Matthew">Hello! Connecting you to Jarvis, your DealMaker AI assistant.</Say>
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
