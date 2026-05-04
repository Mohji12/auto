import pymysql
from pymysql.cursors import DictCursor
import os
from datetime import datetime

# AWS RDS Connection Details
DB_HOST = "mentee.cr82604eu9d2.ap-south-1.rds.amazonaws.com"
DB_PORT = 3306
DB_USER = "admin"
DB_PASSWORD = "Mentee_tracker#2025"
DB_NAME = "harish"

def get_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=DictCursor
    )

def init_db():
    conn = get_connection()
    try:
        with conn.cursor() as c:
            c.execute('''
                CREATE TABLE IF NOT EXISTS email_campaigns (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    subject VARCHAR(255) NOT NULL,
                    total_attempted INT NOT NULL,
                    successful INT NOT NULL,
                    failed INT NOT NULL
                )
            ''')
        conn.commit()
    finally:
        conn.close()

def log_campaign(subject: str, total_attempted: int, successful: int, failed: int):
    conn = get_connection()
    try:
        with conn.cursor() as c:
            c.execute('''
                INSERT INTO email_campaigns (timestamp, subject, total_attempted, successful, failed)
                VALUES (%s, %s, %s, %s, %s)
            ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), subject, total_attempted, successful, failed))
        conn.commit()
    finally:
        conn.close()

def get_analytics_summary():
    conn = get_connection()
    try:
        with conn.cursor() as c:
            # Get total metrics
            c.execute('''
                SELECT 
                    COUNT(id) as total_campaigns,
                    SUM(total_attempted) as total_emails_attempted,
                    SUM(successful) as total_emails_sent,
                    SUM(failed) as total_emails_failed
                FROM email_campaigns
            ''')
            row = c.fetchone()
            
            total_campaigns = row['total_campaigns'] or 0
            # Ensure Decimal returns from SUM are converted back to int
            total_emails_attempted = int(row['total_emails_attempted']) if row['total_emails_attempted'] else 0
            total_emails_sent = int(row['total_emails_sent']) if row['total_emails_sent'] else 0
            total_emails_failed = int(row['total_emails_failed']) if row['total_emails_failed'] else 0
            
            # Calculate success rate safely
            success_rate = 0.0
            if total_emails_attempted > 0:
                success_rate = round((total_emails_sent / total_emails_attempted) * 100, 2)
                
            # Get recent campaigns (last 10)
            c.execute('''
                SELECT id, timestamp, subject, total_attempted, successful, failed 
                FROM email_campaigns 
                ORDER BY timestamp DESC 
                LIMIT 10
            ''')
            
            recent_campaigns = c.fetchall()
            
            # Format datetime objects into ISO format strings for JSON serialization
            for camp in recent_campaigns:
                if isinstance(camp['timestamp'], datetime):
                    camp['timestamp'] = camp['timestamp'].isoformat()
            
            return {
                "total_campaigns": total_campaigns,
                "total_emails_attempted": total_emails_attempted,
                "total_emails_sent": total_emails_sent,
                "total_emails_failed": total_emails_failed,
                "success_rate": success_rate,
                "recent_campaigns": recent_campaigns
            }
    finally:
        conn.close()
