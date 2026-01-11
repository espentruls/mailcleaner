"""
Email categorization using local ML (scikit-learn).
Uses Naive Bayes classifier trained on email features.
Learns from user feedback to improve over time.
"""

import re
import pickle
import json
from pathlib import Path
from typing import List, Tuple, Optional
from collections import Counter

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split

from models import Email, EmailCategory, Database


# Keywords for rule-based classification (fallback/boost)
CATEGORY_KEYWORDS = {
    EmailCategory.SPAM: [
        'urgent', 'winner', 'congratulations', 'claim', 'prize', 'lottery',
        'free money', 'act now', 'limited time', 'click here', 'nigerian',
        'prince', 'inheritance', 'million dollars', 'wire transfer', 'bitcoin',
        'crypto giveaway', 'double your', 'guaranteed'
    ],
    EmailCategory.NEWSLETTER: [
        'newsletter', 'digest', 'weekly', 'monthly', 'roundup', 'update',
        'news', 'bulletin', 'edition', 'issue', 'subscribe', 'unsubscribe',
        'view in browser', 'email preferences'
    ],
    EmailCategory.ADS: [
        'sale', 'discount', 'off', 'deal', 'promo', 'coupon', 'savings',
        'limited offer', 'buy now', 'shop now', 'order now', 'free shipping',
        'clearance', 'flash sale', 'exclusive offer', 'best price'
    ],
    EmailCategory.SOCIAL: [
        'liked your', 'commented on', 'tagged you', 'mentioned you',
        'friend request', 'connection request', 'followed you', 'new follower',
        'linkedin', 'facebook', 'twitter', 'instagram', 'notification'
    ],
    EmailCategory.PROMOTIONS: [
        'upgrade', 'premium', 'pro plan', 'special offer', 'invitation',
        'exclusive', 'vip', 'member', 'reward', 'points', 'cashback',
        'refer a friend', 'loyalty', 'trial', 'beta'
    ],
    EmailCategory.IMPORTANT: [
        'invoice', 'receipt', 'payment', 'confirmation', 'booking',
        'appointment', 'password reset', 'security alert', 'verify',
        'account', 'order confirmation', 'shipping', 'delivery',
        'bank', 'tax', 'contract', 'agreement', 'urgent action required'
    ]
}

# Domains commonly associated with categories
DOMAIN_CATEGORIES = {
    EmailCategory.SOCIAL: [
        'facebook.com', 'linkedin.com', 'twitter.com', 'instagram.com',
        'pinterest.com', 'tiktok.com', 'snapchat.com', 'reddit.com',
        'discord.com', 'slack.com', 'meetup.com'
    ],
    EmailCategory.ADS: [
        'marketing', 'promo', 'deals', 'offers', 'newsletter', 'mail.',
        'campaign', 'mailchimp.com', 'sendgrid.net', 'amazonses.com'
    ],
    EmailCategory.NEWSLETTER: [
        'substack.com', 'mailchimp.com', 'constantcontact.com',
        'medium.com', 'ghost.io', 'buttondown.email', 'revue.co'
    ]
}


class EmailCategorizer:
    def __init__(self, model_path: str = None):
        base_path = Path(__file__).parent.parent / ".tmp"
        base_path.mkdir(parents=True, exist_ok=True)
        self.model_path = model_path or base_path / "categorizer_model.pkl"
        self.vectorizer_path = base_path / "categorizer_vectorizer.pkl"

        self.pipeline = None
        self.is_trained = False
        self._load_model()

    def _load_model(self):
        """Load existing model if available."""
        if Path(self.model_path).exists():
            try:
                with open(self.model_path, 'rb') as f:
                    self.pipeline = pickle.load(f)
                self.is_trained = True
            except Exception as e:
                print(f"Error loading model: {e}")
                self._init_default_model()
        else:
            self._init_default_model()

    def _init_default_model(self):
        """Initialize a new model pipeline."""
        self.pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(
                max_features=5000,
                ngram_range=(1, 2),
                stop_words='english',
                min_df=2
            )),
            ('clf', MultinomialNB(alpha=0.1))
        ])
        self.is_trained = False

    def _prepare_text(self, email: Email) -> str:
        """Combine email fields into text for classification."""
        parts = [
            email.sender_email or '',
            email.subject or '',
            email.snippet or '',
            email.body_preview or ''
        ]
        text = ' '.join(parts).lower()
        # Clean up text
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _keyword_score(self, text: str) -> dict:
        """Score text against category keywords."""
        text_lower = text.lower()
        scores = {}
        for category, keywords in CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            scores[category] = score
        return scores

    def _domain_category(self, email: str) -> Optional[EmailCategory]:
        """Check if sender domain matches known category."""
        email_lower = email.lower()
        for category, domains in DOMAIN_CATEGORIES.items():
            for domain in domains:
                if domain in email_lower:
                    return category
        return None

    def categorize(self, email: Email) -> Tuple[EmailCategory, float]:
        """
        Categorize a single email.
        Returns (category, confidence).
        """
        text = self._prepare_text(email)

        # Try ML model first if trained
        ml_category = None
        ml_confidence = 0.0

        if self.is_trained:
            try:
                proba = self.pipeline.predict_proba([text])[0]
                max_idx = proba.argmax()
                ml_confidence = proba[max_idx]
                ml_category = EmailCategory(self.pipeline.classes_[max_idx])
            except Exception as e:
                print(f"ML prediction error: {e}")

        # Get keyword scores
        keyword_scores = self._keyword_score(text)
        max_keyword_cat = max(keyword_scores, key=keyword_scores.get)
        max_keyword_score = keyword_scores[max_keyword_cat]

        # Check domain-based category
        domain_cat = self._domain_category(email.sender_email)

        # Check if has unsubscribe (strong signal for newsletter/ads)
        has_unsubscribe = bool(email.unsubscribe_link or email.unsubscribe_email)

        # Decision logic
        # 1. If ML is confident (>0.7), trust it
        if ml_confidence > 0.7 and ml_category:
            return ml_category, ml_confidence

        # 2. Strong keyword match (>3 keywords)
        if max_keyword_score >= 3:
            confidence = min(0.5 + (max_keyword_score * 0.1), 0.85)
            return max_keyword_cat, confidence

        # 3. Domain match
        if domain_cat:
            return domain_cat, 0.6

        # 4. Has unsubscribe link -> likely newsletter/promo
        if has_unsubscribe:
            # Check if more newsletter or ads keywords
            if keyword_scores[EmailCategory.NEWSLETTER] > keyword_scores[EmailCategory.ADS]:
                return EmailCategory.NEWSLETTER, 0.5
            elif keyword_scores[EmailCategory.ADS] > 0:
                return EmailCategory.ADS, 0.5
            else:
                return EmailCategory.PROMOTIONS, 0.4

        # 5. ML model with lower confidence
        if ml_confidence > 0.4 and ml_category:
            return ml_category, ml_confidence

        # 6. Weak keyword match
        if max_keyword_score > 0:
            return max_keyword_cat, 0.3

        # 7. Default to uncertain
        return EmailCategory.UNCERTAIN, 0.2

    def categorize_batch(self, emails: List[Email]) -> List[Tuple[EmailCategory, float]]:
        """Categorize multiple emails efficiently."""
        results = []
        for email in emails:
            category, confidence = self.categorize(email)
            email.category = category
            email.category_confidence = confidence
            results.append((category, confidence))
        return results

    def train(self, training_data: List[Tuple[str, str]]):
        """
        Train/retrain the model with labeled data.
        training_data: List of (text, label) tuples
        """
        if len(training_data) < 10:
            print("Not enough training data (minimum 10 samples)")
            return False

        texts, labels = zip(*training_data)

        # Map labels to categories
        valid_categories = [c.value for c in EmailCategory]
        filtered_data = [(t, l) for t, l in zip(texts, labels) if l in valid_categories]

        if len(filtered_data) < 10:
            print("Not enough valid training data")
            return False

        texts, labels = zip(*filtered_data)

        # Train model
        try:
            self.pipeline.fit(texts, labels)
            self.is_trained = True

            # Save model
            with open(self.model_path, 'wb') as f:
                pickle.dump(self.pipeline, f)

            print(f"Model trained on {len(texts)} samples")
            return True
        except Exception as e:
            print(f"Training error: {e}")
            return False

    def train_from_database(self, db: Database):
        """Train model from user feedback stored in database."""
        training_data = db.get_training_data()

        if not training_data:
            print("No training data in database")
            return False

        # Prepare training data
        samples = []
        for row in training_data:
            text = f"{row['sender_email']} {row['subject']} {row['snippet']}"

            # Map user decisions to categories
            label = row['label']
            if label == 'keep':
                # Try to infer category from existing data
                label = EmailCategory.IMPORTANT.value
            elif label == 'delete':
                label = EmailCategory.SPAM.value
            elif label in [c.value for c in EmailCategory]:
                pass  # Already a valid category
            else:
                continue

            samples.append((text, label))

        return self.train(samples)

    def get_category_distribution(self, emails: List[Email]) -> dict:
        """Get distribution of categories across emails."""
        categories = [e.category.value if e.category else 'uncategorized' for e in emails]
        return dict(Counter(categories))


# Pre-trained keywords for bootstrap (used when no user data available)
BOOTSTRAP_TRAINING_DATA = [
    ("winner lottery prize congratulations claim now", "spam"),
    ("newsletter weekly digest unsubscribe", "newsletter"),
    ("sale discount 50% off shop now", "ads"),
    ("john liked your post facebook notification", "social"),
    ("upgrade to premium exclusive offer", "promotions"),
    ("invoice payment receipt order confirmation", "important"),
    ("password reset security verify account", "important"),
    ("free bitcoin crypto double your money", "spam"),
    ("monthly roundup news bulletin", "newsletter"),
    ("flash sale limited time coupon code", "ads"),
    ("new follower twitter mentioned you", "social"),
    ("vip member rewards points cashback", "promotions"),
    ("meeting appointment calendar booking", "important"),
    ("earn money from home work opportunity", "spam"),
    ("daily digest weekly summary update", "newsletter"),
]


def bootstrap_model():
    """Create initial model with bootstrap training data."""
    categorizer = EmailCategorizer()
    categorizer.train(BOOTSTRAP_TRAINING_DATA)
    print("Bootstrap model created")


if __name__ == "__main__":
    # Create bootstrap model for testing
    bootstrap_model()

    # Test categorization
    categorizer = EmailCategorizer()

    test_email = Email(
        id="test1",
        thread_id="test1",
        sender="Newsletter Bot",
        sender_email="newsletter@substack.com",
        subject="Your Weekly Digest",
        snippet="Here's what happened this week in tech...",
        body_preview="View in browser. Unsubscribe. Here's what happened...",
        date=None,
        is_read=True,
        labels=[],
        unsubscribe_link="https://example.com/unsubscribe"
    )

    category, confidence = categorizer.categorize(test_email)
    print(f"Category: {category.value}, Confidence: {confidence:.2f}")
