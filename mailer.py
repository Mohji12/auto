import requests
import json
import base64
import os
import re

def send_email(to_email: str, subject: str, body: str, banner_items: list):
    """
    Sends email using ZeptoMail REST API.
    This is more reliable than SMTP in cloud environments like Railway or AWS Lambda.
    """
    ZEPTO_TOKEN = "PHtE6r0NQr/tgjUv+0RS5qC6QpalMo4uqe1jeFVCsI5FWPYCGk1Sqd4ukmfhr00jXPURHKHKwN9v4OmZserXdDy5YWxOD2qyqK3sx/VYSPOZsbq6x00Zsl4afkLeUYHvcdZo1ifSvdvdNA=="
    SENDER_EMAIL = os.getenv("SENDER_EMAIL", "support@harishcriticalcareclasses.com")
    SENDER_NAME = os.getenv("SENDER_NAME", "Harish Critical Care Classes")
    # Endpoint for .in region
    API_URL = "https://api.zeptomail.in/v1.1/email"

    
    # ZeptoMail API Configuration
    # We use the same token as provided for SMTP

    # Step 1: Format the body (convert newlines to <br> and URLs to buttons)
    formatted_body = body.replace("\n", "<br>")
    url_pattern = r"(https?://\S+)"

    def link_to_button(match):
        url = match.group(0)
        return f"""
        <div style="text-align:center;">
            <a href="{url}" style="display:inline-block;padding:10px 20px;background-color:#00c59a;color:white;text-decoration:none;border-radius:5px;">
                Register Now
            </a>
        </div>
        """

    formatted_body = re.sub(url_pattern, link_to_button, formatted_body)

    # Step 2: Build Banners HTML
    banners_html = ""
    attachments = []
    
    for item in banner_items:
        url = item["url"]
        if item["kind"] == "image":
            banners_html += f'<img src="{url}" alt="Banner" style="width:100%;max-width:100%;height:auto;object-fit:cover;display:block;margin-bottom:12px;" />'
        else:
            safe_name = item.get("filename") or "document.pdf"
            banners_html += f"""
            <div style="text-align:center;margin:12px 0;padding:16px;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc;">
              <p style="margin:0 0 8px 0;color:#334155;font-size:14px;">PDF document</p>
              <a href="{url}" style="display:inline-block;padding:10px 20px;background-color:#1e3a8a;color:white;text-decoration:none;border-radius:5px;font-weight:700;">View / download PDF</a>
              <p style="margin:8px 0 0 0;color:#64748b;font-size:12px;">{safe_name}</p>
            </div>
            """
            # Add PDF as attachment if data is present
            if item.get("data"):
                b64_content = base64.b64encode(item["data"]).decode("utf-8")
                attachments.append({
                    "content": b64_content,
                    "mime_type": "application/pdf",
                    "name": safe_name
                })

    # Step 3: Create Full HTML Body
    html_body = f"""
    <html>
    <body>
        <div style="max-width:600px;margin:auto;background:#fff;padding:20px;">
            {banners_html}
            <div style="margin-top:20px;">{formatted_body}</div>
        </div>
    </body>
    </html>
    """

    # Step 4: Prepare API Payload
    payload = {
        "from": {
            "address": SENDER_EMAIL,
            "name": SENDER_NAME
        },
        "to": [
            {
                "email_address": {
                    "address": to_email
                }
            }
        ],
        "subject": subject,
        "htmlbody": html_body
    }

    if attachments:
        payload["attachments"] = attachments

    # Step 5: Send API Request
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Zoho-enczapikey {ZEPTO_TOKEN}"
    }

    try:
        response = requests.post(API_URL, headers=headers, data=json.dumps(payload))
        
        if response.status_code != 200 and response.status_code != 201:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("details", [{}])[0].get("message", "Unknown error")
            
            # Handle specific error cases for better feedback
            if "verified" in error_msg.lower():
                raise Exception(f"Sender refused: {SENDER_EMAIL} is not verified in ZeptoMail. Error: {error_msg}")
            elif "authorization" in error_msg.lower():
                raise Exception(f"API authentication failed. Please check your token. Error: {error_msg}")
            else:
                raise Exception(f"ZeptoMail API Error (Status {response.status_code}): {error_msg}")
                
        return response.json()
        
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to connect to ZeptoMail API: {str(e)}")
    except Exception as e:
        raise Exception(str(e))
