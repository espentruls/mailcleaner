"""
Ollama Client for local AI-powered email classification and summarization.
Uses qwen2.5:3b model for privacy-focused, on-device processing.
"""

import os
import json
import requests
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass

# Valid categories for classification
VALID_CATEGORIES = [
    'spam', 'newsletter', 'ads', 'social', 
    'promotions', 'important', 'personal', 'uncertain'
]

@dataclass
class OllamaResponse:
    """Response from Ollama API."""
    content: str
    model: str
    done: bool
    total_duration: Optional[int] = None


class OllamaClient:
    """Client for interacting with local Ollama server."""
    
    def __init__(self, host: str = None, model: str = "qwen2.5:3b"):
        """
        Initialize Ollama client.
        
        Args:
            host: Ollama server URL (defaults to OLLAMA_HOST env or localhost)
            model: Model to use for inference
        """
        self.host = host or os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')
        self.model = model
        self.timeout = 60  # seconds
        
    def is_available(self) -> bool:
        """Check if Ollama server is available."""
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def has_model(self) -> bool:
        """Check if the configured model is available."""
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            if response.status_code == 200:
                models = response.json().get('models', [])
                return any(m.get('name', '').startswith(self.model.split(':')[0]) for m in models)
            return False
        except Exception:
            return False
    
    def _generate(self, prompt: str, system: str = None) -> str:
        """
        Generate a response from the model.
        
        Args:
            prompt: The user prompt
            system: Optional system prompt
            
        Returns:
            The generated text response
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,  # Low temp for more deterministic outputs
                "num_predict": 256,  # Limit response length
            }
        }
        
        if system:
            payload["system"] = system
        
        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json().get('response', '').strip()
        except requests.exceptions.Timeout:
            print(f"[OLLAMA] Timeout after {self.timeout}s")
            return ""
        except Exception as e:
            print(f"[OLLAMA] Error: {e}")
            return ""
    
    def classify_email(self, subject: str, sender: str, snippet: str) -> Tuple[str, float]:
        """
        Classify a single email into a category.
        
        Args:
            subject: Email subject
            sender: Sender name/email
            snippet: Email preview text
            
        Returns:
            Tuple of (category, confidence)
        """
        system = """You are an email classifier. Classify emails into exactly ONE category:
- spam: Unsolicited junk, scams, phishing
- newsletter: Regular updates, digests, news
- ads: Marketing, advertisements
- social: Social network notifications
- promotions: Upgrade offers, deals, discounts
- important: Receipts, confirmations, security alerts, work
- personal: Direct messages from real people
- uncertain: Cannot determine

Reply with ONLY the category name in lowercase, nothing else."""

        prompt = f"""Email from: {sender}
Subject: {subject}
Preview: {snippet[:200]}

Category:"""

        response = self._generate(prompt, system)
        category = response.lower().strip()
        
        # Validate category
        if category in VALID_CATEGORIES:
            confidence = 0.85
        else:
            # Try to extract a valid category from the response
            for valid in VALID_CATEGORIES:
                if valid in category:
                    category = valid
                    confidence = 0.7
                    break
            else:
                category = 'uncertain'
                confidence = 0.3
        
        return category, confidence
    
    def summarize_sender_emails(self, sender: str, emails: List[Dict]) -> str:
        """
        Summarize all emails from a specific sender.
        Highlights any outlier emails that differ from typical content.
        
        Args:
            sender: Sender name/email
            emails: List of email dicts with 'subject' and 'snippet' keys
            
        Returns:
            Summary string
        """
        if not emails:
            return "No emails to summarize."
        
        # Take a sample if too many emails
        sample = emails[:20]
        email_list = "\n".join([f"- {e.get('subject', 'No subject')}" for e in sample])
        
        system = """You are an email summarizer. Analyze emails from a single sender and provide:
1. A brief summary of what this sender typically sends (1-2 sentences)
2. If any emails stand out as different or noteworthy, mention them

Be concise. Focus on actionable insights."""

        prompt = f"""Sender: {sender}
Total emails: {len(emails)}

Sample subjects:
{email_list}

Summary:"""

        return self._generate(prompt, system) or f"{len(emails)} emails from {sender}"
    
    def summarize_category(self, category: str, emails: List[Dict]) -> str:
        """
        Summarize all emails in a category.
        Highlights important or interesting emails at the top.
        
        Args:
            category: Category name
            emails: List of email dicts
            
        Returns:
            Summary with highlighted important emails
        """
        if not emails:
            return f"No emails in {category}."
        
        sample = emails[:30]
        email_list = "\n".join([
            f"- From {e.get('sender', 'Unknown')}: {e.get('subject', 'No subject')}"
            for e in sample
        ])
        
        system = """You are an email summarizer. Analyze a category of emails and provide:
1. A brief overview of what's in this category (1-2 sentences)
2. Highlight 2-3 emails that seem most important or interesting
3. Any patterns or trends you notice

Be concise and actionable."""

        prompt = f"""Category: {category}
Total emails: {len(emails)}

Sample emails:
{email_list}

Summary:"""

        return self._generate(prompt, system) or f"{len(emails)} emails in {category}"
    
    def review_uncertain_email(self, subject: str, sender: str, snippet: str) -> Dict:
        """
        Provide detailed review of an uncertain email.
        Includes suggested category, reasoning, and content summary.
        
        Args:
            subject: Email subject
            sender: Sender name/email
            snippet: Email preview text
            
        Returns:
            Dict with 'suggested_category', 'reasoning', 'summary'
        """
        system = """You are an email analyst. For uncertain emails, provide:
1. SUGGESTED_CATEGORY: Your best guess (spam/newsletter/ads/social/promotions/important/personal)
2. REASONING: Why this email is hard to classify (1 sentence)
3. SUMMARY: Brief content summary (1 sentence)

Format your response exactly like:
SUGGESTED_CATEGORY: category_name
REASONING: explanation
SUMMARY: content summary"""

        prompt = f"""Email from: {sender}
Subject: {subject}
Preview: {snippet[:300]}

Analysis:"""

        response = self._generate(prompt, system)
        
        result = {
            'suggested_category': 'uncertain',
            'reasoning': 'Unable to analyze',
            'summary': snippet[:100] if snippet else 'No preview available'
        }
        
        if response:
            lines = response.strip().split('\n')
            for line in lines:
                if line.startswith('SUGGESTED_CATEGORY:'):
                    cat = line.replace('SUGGESTED_CATEGORY:', '').strip().lower()
                    if cat in VALID_CATEGORIES:
                        result['suggested_category'] = cat
                elif line.startswith('REASONING:'):
                    result['reasoning'] = line.replace('REASONING:', '').strip()
                elif line.startswith('SUMMARY:'):
                    result['summary'] = line.replace('SUMMARY:', '').strip()
        
        return result

    def suggest_deletions(self, emails: List[Dict]) -> List[str]:
        """
        Identify emails that are redundant, spam, or low-value ads.
        Returns a list of email IDs suggested for deletion.
        """
        if not emails:
            return []

        # Prepare list for prompt
        email_list_text = ""
        for i, e in enumerate(emails[:50]): # Limit to 50 for context window
            email_list_text += f"ID: {e.get('id')}\nFrom: {e.get('sender')}\nSubject: {e.get('subject')}\nPreview: {e.get('snippet')[:100]}\n---\n"

        system = """You are an intelligent email cleaner. Your task is to identify emails that are clearly SPAM, PROMOTIONAL JUNK, or USELESS NOTIFICATIONS that can be safely deleted.
        
Criteria for deletion:
- Generic unsolicited advertisements
- "You have a new follower" type social spam
- Phishing or scam attempts
- Expired limited time offers

Do NOT delete:
- Personal emails
- Order confirmations / Receipts
- Work related emails
- Newsletters that might be valuable content (unless clearly junk)

Response Format:
Return ONLY a valid JSON array of strings containing the IDs of emails to delete.
Example: ["id_123", "id_456"]
If none, return []."""

        prompt = f"""Review the following emails and identify deletions:

{email_list_text}

JSON Response:"""

        response = self._generate(prompt, system)
        
        try:
            # Clean response to ensure json parsing works
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.endswith("```"):
                response = response[:-3]
            
            deletion_ids = json.loads(response)
            if isinstance(deletion_ids, list):
                return deletion_ids
            return []
        except Exception as e:
            print(f"Error parsing AI suggestions: {e}")
            return []



# Global instance for easy access
ollama_client = None

def get_ollama_client() -> OllamaClient:
    """Get or create the global Ollama client instance."""
    global ollama_client
    if ollama_client is None:
        ollama_client = OllamaClient()
    return ollama_client


if __name__ == "__main__":
    # Test the client
    client = OllamaClient()
    
    print(f"Ollama available: {client.is_available()}")
    print(f"Model available: {client.has_model()}")
    
    if client.is_available():
        # Test classification
        category, confidence = client.classify_email(
            subject="50% OFF Everything This Weekend!",
            sender="promotions@store.com",
            snippet="Don't miss our biggest sale of the year..."
        )
        print(f"Classification: {category} ({confidence:.0%})")
        
        # Test summarization
        summary = client.summarize_sender_emails("promotions@store.com", [
            {"subject": "50% OFF Sale", "snippet": "Big discounts"},
            {"subject": "New arrivals", "snippet": "Check out our new products"},
        ])
        print(f"Summary: {summary}")
