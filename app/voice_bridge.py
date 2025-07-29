import asyncio
import base64
import json
import os
from pathlib import Path
from typing import AsyncIterable
try:
    import audioop
except ImportError:
    # Python 3.13+ compatibility
    import audioop_lts as audioop
import logging
import struct
import time
import wave
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
from jarvis.agent import root_agent

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)

# Audio debugging functions
def analyze_audio_stats(audio_data: bytes, audio_type: str = "PCM") -> dict:
    """Analyze audio data and return statistics"""
    if len(audio_data) < 2:
        return {"error": "Audio data too short"}
    
    try:
        # Convert bytes to 16-bit signed integers
        samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
        
        # Calculate statistics
        max_amp = max(abs(s) for s in samples)
        avg_amp = sum(abs(s) for s in samples) / len(samples)
        rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
        
        # Check for silence (very low amplitude) - lowered threshold
        is_silent = max_amp < 50
        
        return {
            "type": audio_type,
            "samples": len(samples),
            "duration_ms": len(samples) * 1000 // 8000,  # Assuming 8kHz
            "max_amplitude": max_amp,
            "avg_amplitude": avg_amp,
            "rms": rms,
            "is_silent": is_silent,
            "amplitude_range": f"{min(samples)} to {max(samples)}"
        }
    except Exception as e:
        return {"error": f"Failed to analyze: {e}"}

def save_audio_debug(audio_data: bytes, filename: str, sample_rate: int = 8000):
    """Save audio data as WAV file for debugging"""
    try:
        print(f"DEBUG: Saving {filename} with {len(audio_data)} bytes of REAL audio data")
        print(f"DEBUG: First 20 bytes of audio data: {audio_data[:20].hex() if audio_data else 'EMPTY'}")
        
        if len(audio_data) == 0:
            print(f"ERROR: Audio data is completely empty for {filename}! Skipping file creation.")
            return
        
        # Create audio_debug directory if it doesn't exist
        debug_dir = Path(__file__).parent / "audio_debug"
        debug_dir.mkdir(exist_ok=True)
        
        audio_file_path = debug_dir / filename
        print(f"DEBUG: Full path for audio file: {audio_file_path}")
        
        with wave.open(str(audio_file_path), 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_data)
        
        # Verify file was written correctly
        file_size = os.path.getsize(str(audio_file_path))
        print(f"DEBUG: File {filename} written with total size: {file_size} bytes")
        logger.info(f"💾 Saved audio debug file: {filename} ({len(audio_data)} audio bytes, {file_size} total bytes)")
    except Exception as e:
        print(f"ERROR saving audio debug: {e}")
        logger.error(f"❌ Failed to save audio debug: {e}")

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
            agent=root_agent,
            session_service=session_service,
        )
        
        # Track active streams
        self.stream_sid = None
        self.session_id = None
        
        # Audio debugging - accumulate entire call
        self.debug_audio_count = 0
        self.full_call_audio_mulaw = []  # Accumulate all μ-law audio
        self.full_call_audio_pcm = []    # Accumulate all PCM audio
        self.call_start_time = None

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
        logger.info("🎵 Starting Twilio audio stream processing...")
        message_count = 0
        audio_count = 0
        
        while True:
            try:
                message_count += 1
                logger.debug(f"📨 Waiting for message #{message_count}...")
                
                message = await websocket.receive()
                data = json.loads(message)
                event_type = data.get('event', 'unknown')
                
                logger.debug(f"📋 Received event: {event_type}")
                
                if data['event'] == 'start':
                    self.stream_sid = data['start']['streamSid']
                    call_sid = data['start'].get('callSid', 'unknown')
                    logger.info(f"📞 Call started - StreamSID: {self.stream_sid}, CallSID: {call_sid}")
                    
                    # Initialize ADK session for this call
                    await self.start_agent_session(call_sid)
                    logger.info("✅ ADK session initialized")
                    
                    # Initialize full call audio recording
                    self.call_start_time = int(time.time())
                    self.full_call_audio_mulaw.clear()
                    self.full_call_audio_pcm.clear()
                    print(f"🎙️ STARTED RECORDING FULL CALL AUDIO at {self.call_start_time}")
                    
                elif data['event'] == 'media':
                    audio_count += 1
                    self.debug_audio_count += 1
                    
                    # Extract and convert audio from Twilio format
                    audio_data = data['media']['payload']  # Base64 encoded μ-law
                    decoded_audio = base64.b64decode(audio_data)
                    
                    # Convert μ-law to 16-bit PCM
                    pcm_audio = audioop.ulaw2lin(decoded_audio, 2)
                    
                    # Audio debugging and analysis
                    if audio_count % 25 == 0:
                        # Analyze μ-law audio (as raw bytes)
                        mulaw_stats = {
                            "type": "μ-law",
                            "bytes": len(decoded_audio),
                            "first_bytes": decoded_audio[:8].hex() if len(decoded_audio) >= 8 else "N/A"
                        }
                        
                        # Analyze PCM audio
                        pcm_stats = analyze_audio_stats(pcm_audio, "PCM")
                        
                        logger.info(f"🎤 Audio #{audio_count}:")
                        logger.info(f"  μ-law: {mulaw_stats}")
                        logger.info(f"  PCM: {pcm_stats}")
                        
                        # Check for potential issues
                        if pcm_stats.get('is_silent'):
                            logger.warning("⚠️ Audio appears to be silent!")
                        if pcm_stats.get('max_amplitude', 0) > 30000:
                            logger.warning("⚠️ Audio may be clipping!")
                    
                    # Accumulate audio for full call recording
                    self.full_call_audio_mulaw.append(decoded_audio)
                    self.full_call_audio_pcm.append(pcm_audio)
                    
                    # Debug audio details every 50 packets
                    if self.debug_audio_count % 50 == 0:
                        print(f"🎧 AUDIO PACKET #{self.debug_audio_count}:")
                        print(f"  📥 Raw μ-law: {len(decoded_audio)} bytes -> {decoded_audio[:10].hex()}")
                        print(f"  🔄 PCM conversion: {len(pcm_audio)} bytes -> {pcm_audio[:20].hex()}")
                        print(f"  📊 Total accumulated: μ-law={len(self.full_call_audio_mulaw)} packets, PCM={len(self.full_call_audio_pcm)} packets")
                        
                        total_mulaw_bytes = sum(len(chunk) for chunk in self.full_call_audio_mulaw)
                        total_pcm_bytes = sum(len(chunk) for chunk in self.full_call_audio_pcm)
                        print(f"  📈 Total audio data: μ-law={total_mulaw_bytes} bytes, PCM={total_pcm_bytes} bytes")
                    
                    yield pcm_audio
                    
                elif data['event'] == 'stop':
                    logger.info("📞 Call ended by Twilio")
                    
                    # Save full call audio
                    await self.save_full_call_audio()
                    break
                else:
                    logger.warning(f"⚠️ Unknown event type: {event_type}")
                    
            except Exception as e:
                logger.error(f"❌ Error processing Twilio stream: {e}")
                logger.error(f"❌ Error type: {type(e).__name__}")
                import traceback
                logger.error(f"❌ Traceback: {traceback.format_exc()}")
                break
        
        logger.info(f"🏁 Audio stream ended. Messages: {message_count}, Audio packets: {audio_count}")

    async def save_full_call_audio(self):
        """Save the complete audio from the entire call"""
        if not self.full_call_audio_mulaw or not self.full_call_audio_pcm:
            print("⚠️ No audio data to save")
            return
            
        try:
            # Combine all audio chunks
            full_mulaw = b''.join(self.full_call_audio_mulaw)
            full_pcm = b''.join(self.full_call_audio_pcm)
            
            # Create filenames with call timestamp
            call_duration = len(self.full_call_audio_pcm) * 20  # 20ms per packet
            mulaw_filename = f"full_call_mulaw_{self.call_start_time}_{call_duration}ms.wav"
            pcm_filename = f"full_call_pcm_{self.call_start_time}_{call_duration}ms.wav"
            
            print(f"💾 SAVING FULL CALL AUDIO:")
            print(f"  📊 Total packets: {len(self.full_call_audio_pcm)}")
            print(f"  ⏱️ Call duration: ~{call_duration}ms ({call_duration/1000:.1f} seconds)")
            print(f"  📥 μ-law audio: {len(full_mulaw)} bytes")
            print(f"  🔄 PCM audio: {len(full_pcm)} bytes")
            
            # Convert μ-law to PCM for WAV saving (μ-law is compressed format)
            mulaw_as_pcm = audioop.ulaw2lin(full_mulaw, 2)
            save_audio_debug(mulaw_as_pcm, mulaw_filename, 8000)
            
            # Save PCM audio (this is what actually went to Gemini)
            save_audio_debug(full_pcm, pcm_filename, 8000)
            
            print(f"✅ Saved complete call audio files:")
            print(f"  📁 {mulaw_filename}")
            print(f"  📁 {pcm_filename}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save full call audio: {e}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")

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
            logger.info(f"🔧 Using model: {self.model_id}")
            
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
                logger.info("🎵 Creating audio stream...")
                
                audio_stream = self.twilio_audio_stream()
                logger.info("📡 Starting streaming to Gemini Live...")
                
                # Start streaming audio from Twilio to Gemini
                response_count = 0
                audio_sent_count = 0
                
                # Log audio format being sent to Gemini
                logger.info("🎵 Audio format for Gemini Live:")
                logger.info("  📊 Format: 16-bit PCM, Mono")
                logger.info("  📊 Sample Rate: 8kHz (Twilio standard)")
                logger.info("  📊 MIME Type: audio/pcm")
                
                async for response in session.start_stream(
                    stream=audio_stream, 
                    mime_type='audio/pcm'
                ):
                    response_count += 1
                    logger.info(f"🔄 Received response #{response_count} from Gemini Live")
                    try:
                        # Debug: Log all response types to understand what Gemini is sending
                        logger.info(f"🔄 Received response from Gemini Live: type={type(response)}, data={hasattr(response, 'data')}, text={hasattr(response, 'text')}")
                        
                        # Handle different types of responses from Gemini
                        if hasattr(response, 'data') and response.data:
                            # Audio response from Gemini - send back to Twilio
                            print(f"🔊 GEMINI AUDIO RESPONSE #{response_count}:")
                            print(f"  📤 Received from Gemini: {len(response.data)} bytes -> {response.data[:20].hex()}")
                            
                            audio_payload = self.convert_audio_to_mulaw(response.data)
                            if audio_payload:
                                print(f"  📞 Converted to μ-law: {len(audio_payload)} chars (base64)")
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
                            print(f"📝 GEMINI TEXT RESPONSE #{response_count}: {response.text}")
                            logger.info(f"📝 Processing text through ADK: {response.text}")
                            
                            # Process through your ADK agent for enhanced responses
                            enhanced_response = await self.process_with_adk_agent(response.text)
                            print(f"🤖 ADK ENHANCED RESPONSE: {enhanced_response}")
                            
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
                        logger.error(f"❌ Error processing Gemini response: {e}")
                
                logger.info("🏁 Finished processing Gemini Live responses")
                            
        except Exception as e:
            logger.error(f"❌ Voice call handler error: {e}")
            logger.error(f"❌ Error type: {type(e).__name__}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
        finally:
            logger.info("🔚 Voice call handler function ended")
            # Send error message to caller
            error_message = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": base64.b64encode(b"Sorry, I encountered a technical issue.").decode()}
            }
            await websocket.send(json.dumps(error_message))

# Quart app routes
@app.route('/twiml', methods=['POST'])
@app.route('/twiml/', methods=['POST'])  # Handle both with and without trailing slash
async def handle_incoming_call():
    """TwiML endpoint for incoming calls"""
    logger.info("📞 Incoming call received")
    
    # Get the base URL for WebSocket connection - detect if using ngrok
    # Check ngrok headers to determine the correct URL
    forwarded_host = request.headers.get('X-Forwarded-Host')
    forwarded_proto = request.headers.get('X-Forwarded-Proto')
    
    if forwarded_host and 'ngrok' in forwarded_host:
        # Request comes through ngrok - use secure WebSocket
        websocket_url = f"wss://{forwarded_host}/voice"
        logger.info(f"🔒 Using ngrok WebSocket URL: {websocket_url}")
    elif forwarded_proto == 'https':
        # HTTPS request - use secure WebSocket
        host = request.headers.get('Host', request.url_root.split('//')[1].rstrip('/'))
        websocket_url = f"wss://{host}/voice"
        logger.info(f"🔒 Using secure WebSocket URL: {websocket_url}")
    else:
        # Local development fallback
        base_url = request.url_root.replace('http', 'ws').rstrip('/')
        websocket_url = f"{base_url}/voice"
        logger.info(f"🏠 Using local WebSocket URL: {websocket_url}")
    
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
    <Say voice="alice">Hello! Connecting you to Dealmaker AI assistant.</Say>
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
    logger.info(f"🔍 WebSocket headers: {dict(websocket.headers)}")
    
    bridge = JarvisVoiceBridge()
    
    try:
        logger.info("🚀 Starting voice call handler...")
        await bridge.handle_voice_call()
        logger.info("✅ Voice call handler completed successfully")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        logger.error(f"❌ Error type: {type(e).__name__}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
    finally:
        logger.info("🔌 WebSocket connection closed")

@app.route('/health')
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Jarvis Voice Bridge"}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
