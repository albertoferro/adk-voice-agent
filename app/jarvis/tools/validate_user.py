"""
User validation tool for DealMaker API integration.
"""

import requests
import urllib3
import ssl

# Disable SSL warnings and verification for development environment
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Create a custom SSL context that doesn't verify certificates
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


def test_connectivity() -> dict:
    """
    Test basic connectivity to the DealMaker API.
    
    Returns:
        dict: Connectivity test results
    """
    try:
        print("🌐 CONNECTIVITY_TEST: Testing basic connectivity...")
        response = requests.get("https://app.dealmaker-dev.com", timeout=10, verify=False)
        print(f"✅ CONNECTIVITY_TEST: Status = {response.status_code}")
        return {
            "success": True,
            "status_code": response.status_code,
            "message": "Connectivity test successful"
        }
    except Exception as e:
        print(f"❌ CONNECTIVITY_TEST: Failed = {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "message": "Connectivity test failed"
        }


def send_otp(email: str) -> dict:
    """
    Send OTP code to user's email for authentication.

    Args:
        email (str): User's email address

    Returns:
        dict: Status of OTP sending operation
    """
    try:
        url = "https://app.dealmaker-dev.com/api/login/send_otp"
        
        # Prepare form data
        data = {
            'email': email
        }
        
        # Test connectivity first
        connectivity = test_connectivity()
        print(f"🌐 SEND_OTP: Connectivity test = {connectivity}")
        
        # Prepare headers with more browser-like headers
        headers = {
            'Cookie': '__profilin=p%3Dt',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        print(f"🚀 SEND_OTP: Starting request to {url}")
        print(f"📧 SEND_OTP: Email = {email}")
        print(f"📋 SEND_OTP: Data = {data}")
        print(f"🔧 SEND_OTP: Headers = {headers}")
        
        # Make the request
        print("📡 SEND_OTP: Making POST request...")
        response = requests.post(url, data=data, headers=headers, timeout=30, verify=False)
        
        print(f"✅ SEND_OTP: Response status code = {response.status_code}")
        print(f"📄 SEND_OTP: Response headers = {dict(response.headers)}")
        print(f"📝 SEND_OTP: Response text = {response.text[:500]}...")  # First 500 chars
        
        if response.status_code in [200, 201]:
            return {
                "success": True,
                "message": f"OTP code has been sent to {email}. Please check your email and provide the code when ready.",
                "email": email,
                "status_code": response.status_code,
                "response_data": response.text
            }
        else:
            return {
                "success": False,
                "message": f"Failed to send OTP. Status code: {response.status_code}",
                "email": email,
                "status_code": response.status_code,
                "error": response.text
            }
            
    except requests.exceptions.RequestException as e:
        print(f"❌ SEND_OTP: Network error = {str(e)}")
        print(f"❌ SEND_OTP: Error type = {type(e).__name__}")
        return {
            "success": False,
            "message": f"Network error occurred while sending OTP: {str(e)}",
            "email": email,
            "error": str(e),
            "error_type": type(e).__name__
        }
    except Exception as e:
        print(f"❌ SEND_OTP: Unexpected error = {str(e)}")
        print(f"❌ SEND_OTP: Error type = {type(e).__name__}")
        return {
            "success": False,
            "message": f"Unexpected error occurred: {str(e)}",
            "email": email,
            "error": str(e),
            "error_type": type(e).__name__
        }


def verify_otp(email: str, code: str) -> dict:
    """
    Verify OTP code and get authentication token.

    Args:
        email (str): User's email address
        code (str): OTP code received via email

    Returns:
        dict: Authentication result with bearer token if successful
    """
    try:
        url = "https://app.dealmaker-dev.com/api/login/verify_otp"
        
        # Prepare form data
        data = {
            'email': email,
            'code': code
        }
        
        # Test connectivity first
        connectivity = test_connectivity()
        print(f"🌐 VERIFY_OTP: Connectivity test = {connectivity}")
        
        # Prepare headers with more browser-like headers
        headers = {
            'Cookie': '__profilin=p%3Dt',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        print(f"🚀 VERIFY_OTP: Starting request to {url}")
        print(f"📧 VERIFY_OTP: Email = {email}")
        print(f"🔐 VERIFY_OTP: Code = {code}")
        print(f"📋 VERIFY_OTP: Data = {data}")
        print(f"🔧 VERIFY_OTP: Headers = {headers}")
        
        # Make the request
        print("📡 VERIFY_OTP: Making POST request...")
        response = requests.post(url, data=data, headers=headers, timeout=30, verify=False)
        
        print(f"✅ VERIFY_OTP: Response status code = {response.status_code}")
        print(f"📄 VERIFY_OTP: Response headers = {dict(response.headers)}")
        print(f"📝 VERIFY_OTP: Response text = {response.text[:500]}...")  # First 500 chars
        
        if response.status_code in [200, 201]:
            # Try to extract bearer token from response
            try:
                response_data = response.json()
                # Try different possible token field names and nested structures
                bearer_token = (
                    response_data.get('token') or 
                    response_data.get('access_token') or 
                    response_data.get('bearer_token') or
                    response_data.get('data', {}).get('token') or
                    response_data.get('data', {}).get('access_token') or
                    response_data.get('data', {}).get('bearer_token')
                )
                
                return {
                    "success": True,
                    "message": "User successfully authenticated!",
                    "email": email,
                    "bearer_token": bearer_token,
                    "response_data": response_data,
                    "status_code": response.status_code
                }
            except Exception as json_error:
                # If JSON parsing fails, still return success but note the token extraction issue
                return {
                    "success": True,
                    "message": "User authenticated but could not extract token from response",
                    "email": email,
                    "bearer_token": None,
                    "raw_response": response.text,
                    "status_code": response.status_code,
                    "json_error": str(json_error)
                }
        else:
            return {
                "success": False,
                "message": f"OTP verification failed. Status code: {response.status_code}. Please try again with the correct code.",
                "email": email,
                "code": code,
                "status_code": response.status_code,
                "error": response.text
            }
            
    except requests.exceptions.RequestException as e:
        print(f"❌ VERIFY_OTP: Network error = {str(e)}")
        print(f"❌ VERIFY_OTP: Error type = {type(e).__name__}")
        return {
            "success": False,
            "message": f"Network error occurred during OTP verification: {str(e)}",
            "email": email,
            "code": code,
            "error": str(e),
            "error_type": type(e).__name__
        }
    except Exception as e:
        print(f"❌ VERIFY_OTP: Unexpected error = {str(e)}")
        print(f"❌ VERIFY_OTP: Error type = {type(e).__name__}")
        return {
            "success": False,
            "message": f"Unexpected error occurred: {str(e)}",
            "email": email,
            "code": code,
            "error": str(e),
            "error_type": type(e).__name__
        }


def debug_api_connection() -> dict:
    """
    Debug function to test API connectivity and provide detailed diagnostics.
    
    Returns:
        dict: Detailed diagnostic information
    """
    print("🔍 DEBUG: Starting comprehensive API diagnostics...")
    
    # Test basic connectivity
    connectivity = test_connectivity()
    
    # Test DNS resolution
    try:
        import socket
        host = "app.dealmaker-dev.com"
        ip = socket.gethostbyname(host)
        dns_info = {"success": True, "host": host, "ip": ip}
        print(f"🌐 DEBUG: DNS resolution = {dns_info}")
    except Exception as e:
        dns_info = {"success": False, "error": str(e)}
        print(f"❌ DEBUG: DNS resolution failed = {str(e)}")
    
    # Test SSL/TLS (with verification disabled for dev environment)
    try:
        import socket
        context = ssl_context  # Use our unverified context
        with socket.create_connection(("app.dealmaker-dev.com", 443), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname="app.dealmaker-dev.com") as ssock:
                ssl_info = {"success": True, "version": ssock.version(), "cipher": ssock.cipher(), "note": "SSL verification disabled for dev environment"}
                print(f"🔒 DEBUG: SSL/TLS connection = {ssl_info}")
    except Exception as e:
        ssl_info = {"success": False, "error": str(e)}
        print(f"❌ DEBUG: SSL/TLS connection failed = {str(e)}")
    
    return {
        "connectivity": connectivity,
        "dns": dns_info,
        "ssl": ssl_info,
        "message": "Diagnostic complete. Check logs for detailed information."
    }


def validate_user(email: str = "", code: str = "") -> dict:
    """
    Main validation function that handles the two-step OTP process.
    
    If only email is provided, sends OTP.
    If both email and code are provided, verifies OTP.

    Args:
        email (str): User's email address
        code (str): OTP code (optional, required for verification step)

    Returns:
        dict: Result of the validation process
    """
    if not email:
        return {
            "success": False,
            "message": "Email is required for user validation. Please provide your email address.",
            "step": "email_required"
        }
    
    if not code:
        # Step 1: Send OTP
        result = send_otp(email)
        if result["success"]:
            result["step"] = "otp_sent"
            result["message"] += " Once you receive the code, please provide it to complete the validation."
        return result
    else:
        # Step 2: Verify OTP
        result = verify_otp(email, code)
        if result["success"]:
            result["step"] = "validation_complete"
        else:
            result["step"] = "verification_failed"
        return result 