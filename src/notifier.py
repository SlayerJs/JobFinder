import os
import json
import logging
import requests
from src.models import JobPosting

logger = logging.getLogger(__name__)

class DiscordNotifier:
    def __init__(self):
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    def send_job_alert(self, job: JobPosting, ai_reason: str, tier: str = "NONE"):
        if not self.webhook_url:
            logger.warning("Discord webhook URL not configured. Skipping alert.")
            return False

        # Colors based on Tier
        color = 0x00FF00 # Default Green
        tier_label = "✅ Approved Job"
        
        if "1" in tier:
            color = 0xFFD700 # Gold
            tier_label = "🥇 Tier 1: Direct Match"
        elif "2" in tier:
            color = 0xC0C0C0 # Silver
            tier_label = "🥈 Tier 2: Strong Match"
        elif "3" in tier:
            color = 0xCD7F32 # Bronze
            tier_label = "🎯 Tier 3: Adjacent Match"
        elif tier.upper() != "NONE":
            tier_label = f"✅ Approved ({tier})"

        embed = {
            "title": f"{tier_label} | {job.title}",
            "url": job.url,
            "color": color,
            "fields": [
                {"name": "Company", "value": job.company, "inline": True},
                {"name": "Location", "value": job.location, "inline": True},
                {"name": "Source", "value": job.source, "inline": True},
                {"name": "AI Evaluation", "value": ai_reason, "inline": False}
            ],
            "footer": {"text": "JobFinder AI Pipeline"}
        }

        embed['title'] = embed['title'][:256]
        for field in embed['fields']:
            field['value'] = str(field['value'] or 'Unknown')[:1024]
        payload = {"embeds": [embed], "allowed_mentions": {"parse": []}}

        try:
            res = requests.post(self.webhook_url, json=payload, timeout=10)
            if res.status_code not in (200, 204):
                logger.error(f"Discord Webhook failed: {res.status_code} - {res.text}")
            return res.status_code in (200, 204)
        except Exception:
            logger.error("Error sending Discord notification")
            return False

    def send_run_summary(self, filepath: str, total_processed: int, approved_count: int):
        """Uploads the Excel report file directly to the Discord channel."""
        if not self.webhook_url:
            return False
            
        filename = os.path.basename(filepath)
        
        # We attach a small message explaining the file upload
        payload = {
            "content": f"📊 **AI Processing Cycle Complete!**\nProcessed `{total_processed}` jobs. Found `{approved_count}` matches. See attached report for details."
        }
        
        try:
            with open(filepath, "rb") as f:
                # Discord Webhooks require multipart/form-data for file uploads
                files = {
                    "file": (filename, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                }
                data = {
                    "payload_json": json.dumps(payload)
                }
                res = requests.post(self.webhook_url, data=data, files=files, timeout=15)
                if res.status_code not in (200, 204):
                    logger.error(f"Failed to upload Discord summary: {res.status_code} - {res.text}")
                else:
                    logger.info("✅ Summary report successfully uploaded to Discord!")
        except Exception:
            logger.error("Error uploading summary to Discord")
