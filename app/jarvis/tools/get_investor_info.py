"""
Investor information tool for DealMaker API integration.
"""

import requests
import urllib3

# Disable SSL warnings for development environment
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_investor_info(email: str, access_token: str) -> dict:
    """
    Get investor information using access token.

    Args:
        email (str): Investor's email address
        access_token (str): Bearer token obtained from user validation

    Returns:
        dict: Investor information or error details
    """
    try:
        url = "https://app.dealmaker-dev.com/api/users/investments"
        
        # Prepare query parameters
        params = {
            'email': email
        }
        
        # Prepare headers with authorization
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Cookie': '__profilin=p%3Dt',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive'
        }
        
        print(f"🚀 GET_INVESTOR_INFO: Starting request to {url}")
        print(f"📧 GET_INVESTOR_INFO: Email = {email}")
        print(f"🔐 GET_INVESTOR_INFO: Access token = {access_token[:20]}...")  # Only show first 20 chars for security
        print(f"📋 GET_INVESTOR_INFO: Params = {params}")
        print(f"🔧 GET_INVESTOR_INFO: Headers = {headers}")
        
        # Make the request
        print("📡 GET_INVESTOR_INFO: Making GET request...")
        response = requests.get(url, params=params, headers=headers, timeout=30, verify=False)
        
        print(f"✅ GET_INVESTOR_INFO: Response status code = {response.status_code}")
        print(f"📄 GET_INVESTOR_INFO: Response headers = {dict(response.headers)}")
        print(f"📝 GET_INVESTOR_INFO: Response text = {response.text[:1000]}...")  # First 1000 chars
        
        if response.status_code in [200, 201]:
            try:
                response_data = response.json()
                return {
                    "success": True,
                    "message": "Investor information retrieved successfully",
                    "email": email,
                    "investor_data": response_data,
                    "status_code": response.status_code
                }
            except Exception as json_error:
                return {
                    "success": True,
                    "message": "Data retrieved but could not parse JSON response",
                    "email": email,
                    "raw_response": response.text,
                    "status_code": response.status_code,
                    "json_error": str(json_error)
                }
        else:
            return {
                "success": False,
                "message": f"Failed to get investor information. Status code: {response.status_code}",
                "email": email,
                "status_code": response.status_code,
                "error": response.text
            }
            
    except requests.exceptions.RequestException as e:
        print(f"❌ GET_INVESTOR_INFO: Network error = {str(e)}")
        print(f"❌ GET_INVESTOR_INFO: Error type = {type(e).__name__}")
        return {
            "success": False,
            "message": f"Network error occurred while getting investor information: {str(e)}",
            "email": email,
            "access_token": access_token[:20] + "...",  # Only show first 20 chars
            "error": str(e),
            "error_type": type(e).__name__
        }
    except Exception as e:
        print(f"❌ GET_INVESTOR_INFO: Unexpected error = {str(e)}")
        print(f"❌ GET_INVESTOR_INFO: Error type = {type(e).__name__}")
        return {
            "success": False,
            "message": f"Unexpected error occurred: {str(e)}",
            "email": email,
            "access_token": access_token[:20] + "...",  # Only show first 20 chars
            "error": str(e),
            "error_type": type(e).__name__
        }


def format_investor_data(investor_data: dict) -> str:
    """
    Format investor data into a human-readable summary.
    
    Args:
        investor_data (dict): Raw investor data from API
    
    Returns:
        str: Formatted investor information
    """
    try:
        if not investor_data or not isinstance(investor_data, dict):
            return "No investor data available."
        
        items = investor_data.get('items', [])
        if not items:
            return "No investment information found."
        
        # Get the first (main) investment record
        investor = items[0]
        
        # Extract key information
        name = investor.get('name', 'Unknown')
        email = investor.get('user', {}).get('email', 'Unknown')
        state = investor.get('state', 'Unknown')
        funding_state = investor.get('funding_state', 'Unknown')
        currency = investor.get('investor_currency', 'USD')
        investment_value = investor.get('investment_value', 0)
        allocated_amount = investor.get('allocated_amount', 0)
        num_securities = investor.get('number_of_securities', 0)
        funds_value = investor.get('funds_value', 0)
        created_date = investor.get('created_at', '')
        
        # Format date
        formatted_date = ""
        if created_date:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(created_date.replace('Z', '+00:00'))
                formatted_date = dt.strftime('%B %d, %Y')
            except:
                formatted_date = created_date
        
        # Build summary
        summary = f"""
📊 **Investor Profile Summary**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

👤 **Name:** {name}
📧 **Email:** {email}
📅 **Member Since:** {formatted_date}

💼 **Investment Status:**
   • Current State: {state.title()}
   • Funding Status: {funding_state.title()}
   
💰 **Financial Summary:**
   • Investment Value: {currency} {investment_value:,.2f}
   • Allocated Amount: {currency} {allocated_amount:,.2f}
   • Funds Value: {currency} {funds_value:,.2f}
   • Securities Owned: {num_securities:,}

📈 **Portfolio:** {len(items)} investment(s) found
        """.strip()
        
        return summary
        
    except Exception as e:
        return f"Error formatting investor data: {str(e)}"


def get_investor_investments(email: str, access_token: str) -> dict:
    """
    Get detailed investor investments using access token.
    This is an alias for get_investor_info with more descriptive name.

    Args:
        email (str): Investor's email address
        access_token (str): Bearer token obtained from user validation

    Returns:
        dict: Investor investment information or error details
    """
    return get_investor_info(email, access_token) 