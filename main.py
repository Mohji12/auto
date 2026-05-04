import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import uuid
import boto3
import shutil
from typing import List, Optional
from fastapi import FastAPI, UploadFile, Form, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.mailer import send_email
import pandas as pd
from io import StringIO, BytesIO  # Correct imports for StringIO and BytesIO
from mangum import Mangum  # Add Mangum to handle the Lambda integration
from app.database import init_db, log_campaign, get_analytics_summary # Import DB analytics

app = FastAPI()

# Initialize analytics database on startup
@app.on_event("startup")
def startup_event():
    init_db()

# Enable CORS (customize for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to your React frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# S3 Configuration
S3_BUCKET_NAME = "cedat1"
S3_REGION = "ap-south-1"

@app.get("/")
def root():
    return {"message": "Email Automation API", "docs": "POST /send-emails, GET /api/analytics"}

def _content_type_for_banner(filename: str) -> str:
    lower = (filename or "").lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".bmp"):
        return "image/bmp"
    if lower.endswith(".svg"):
        return "image/svg+xml"
    if lower.endswith(".pdf"):
        return "application/pdf"
    return "application/octet-stream"


def _banner_kind(filename: str) -> Optional[str]:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"):
        return "image"
    return None


def _content_type_for_recipient_file(filename: str) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".csv"):
        return "text/csv; charset=utf-8"
    if lower.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if lower.endswith(".xls"):
        return "application/vnd.ms-excel"
    return "application/octet-stream"


def _upload_recipient_list_to_s3(
    bucket_name: str, file_body: bytes, original_filename: str
) -> Optional[str]:
    """Store CSV/Excel in S3 under recipient-lists/ (private object, no public ACL). Returns object key or None."""
    safe_base = os.path.basename(original_filename or "recipients.csv").replace("\\", "_").replace("/", "_")
    key = f"recipient-lists/{uuid.uuid4().hex}_{safe_base}"
    ctype = _content_type_for_recipient_file(safe_base)
    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=file_body,
            ContentType=ctype,
        )
        return key
    except Exception as e:
        print(f"Warning: Could not upload recipient list to S3: {e}")
        return None


@app.post("/send-emails")
async def send_emails(
    subject: str = Form(...),
    content: str = Form(...),
    banners: List[UploadFile] = File(...),
    csv_file: UploadFile = File(...),
):
    if not banners:
        return JSONResponse(
            status_code=400,
            content={"error": "Please upload at least one banner image or PDF."},
        )

    banner_items = []

    try:
        bucket_name = S3_BUCKET_NAME
        region = S3_REGION

        for uf in banners:
            raw = await uf.read()
            if not raw:
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Empty file: {uf.filename or 'unknown'}"},
                )

            orig_name = uf.filename or "file"
            safe_base = os.path.basename(orig_name).replace("\\", "_").replace("/", "_")
            unique_key = f"{uuid.uuid4().hex}_{safe_base}"
            content_type = _content_type_for_banner(safe_base)
            kind = _banner_kind(safe_base)

            if kind is None:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": f"Unsupported banner type: {safe_base}. Use images (JPG, PNG, GIF, WebP, SVG, BMP) or PDF."
                    },
                )

            try:
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=unique_key,
                    Body=raw,
                    ContentType=content_type,
                    ACL="public-read",
                )
            except Exception as acl_error:
                print(f"Warning: Could not set ACL during upload: {str(acl_error)}")
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=unique_key,
                    Body=raw,
                    ContentType=content_type,
                )
                try:
                    s3_client.put_object_acl(
                        Bucket=bucket_name,
                        Key=unique_key,
                        ACL="public-read",
                    )
                except Exception as acl_error2:
                    print(f"Warning: Could not set ACL separately: {str(acl_error2)}")
                    print(
                        "Note: The file may not be accessible. Please configure bucket public access or IAM permissions."
                    )

            banner_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{unique_key}"
            item = {"url": banner_url, "kind": kind, "filename": safe_base}
            if kind == "pdf":
                item["data"] = raw
            banner_items.append(item)

    except Exception as e:
        return JSONResponse(
            status_code=500, content={"error": f"Failed to upload banners to S3: {str(e)}"}
        )

    # Step 3: Read the CSV/Excel file
    contents = await csv_file.read()
    if not contents:
        return JSONResponse(status_code=400, content={"error": "Recipient file is empty."})

    recipient_s3_key = _upload_recipient_list_to_s3(
        bucket_name, contents, csv_file.filename or "recipients.csv"
    )

    # Step 4: Use pandas to handle CSV/Excel dynamically (CSV or Excel)
    fname = (csv_file.filename or "").lower()
    try:
        if fname.endswith(".csv"):
            # For CSV files, try different encodings
            try:
                content_str = contents.decode("utf-8")
                data = pd.read_csv(StringIO(content_str))
            except UnicodeDecodeError:
                # Try with different encoding if UTF-8 fails
                content_str = contents.decode("latin-1")
                data = pd.read_csv(StringIO(content_str))
        elif fname.endswith((".xls", ".xlsx")):
            # For Excel files, use BytesIO instead of StringIO
            from io import BytesIO
            data = pd.read_excel(BytesIO(contents))
        else:
            raise ValueError("Unsupported file format. Please upload a CSV or Excel file.")
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Failed to read file: {str(e)}"})

    # Step 5: Find the email column dynamically (case-insensitive)
    email_column = None
    for col in data.columns:
        if col.strip().lower() in ["email", "email address"]:
            email_column = col
            break

    if not email_column:
        return JSONResponse(status_code=400, content={"error": "Email column not found in the file."})

    emails = data[email_column].dropna().astype(str).tolist()

    # Step 6: Send emails
    successful_count = 0
    failed_count = 0
    
    for email in emails:
        try:
            send_email(email, subject, content, banner_items)
            successful_count += 1
        except Exception as e:
            print(f"Failed to send email to {email}: {e}")
            failed_count += 1

    # Log to analytics database
    try:
        log_campaign(subject, len(emails), successful_count, failed_count)
    except Exception as e:
        print(f"Failed to log campaign analytics: {e}")

    out = {
        "message": f"Emails sent! Successful: {successful_count}, Failed: {failed_count}",
    }
    if recipient_s3_key:
        out["recipient_file_s3_key"] = recipient_s3_key
        out["recipient_file_s3_uri"] = f"s3://{bucket_name}/{recipient_s3_key}"
    return out

@app.get("/api/analytics")
async def get_analytics():
    try:
        summary = get_analytics_summary()
        return summary
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to fetch analytics: {str(e)}"})

# Lambda handler for AWS Lambda
handler = Mangum(app)