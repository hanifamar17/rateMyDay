# Sentiment analysis
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
import torch.nn.functional as F

# Generate wordcloud using TF-IDF
from wordcloud import WordCloud, STOPWORDS
from sklearn.feature_extraction.text import TfidfVectorizer
from nltk.corpus import stopwords as nltk_stopwords
import nltk

# Heatmap sentiment
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import base64
from io import BytesIO
import mysql.connector
from datetime import datetime, date, timedelta

# Moving avg sentiment
from collections import defaultdict

# KONFIGURASI DATABASE
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="ratemydays"
    )

# Load model & tokenizer (sekali saja saat init)
model_name = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(model_name)
sentiment_pipeline = pipeline("sentiment-analysis", model=model, tokenizer=tokenizer)

# Custom label mapping
id2label = model.config.id2label  # e.g., {0: 'negative', 1: 'neutral', 2: 'positive'}

# Sentiment Analysis
def analyze_sentiment(text):
    """
    Analyze sentiment using cardiffnlp/twitter-xlm-roberta-base-sentiment

    Returns:
        tuple: (score, label) - score in range [-1.0, 1.0], label is 'negative', 'neutral', or 'positive'
    """
    if not text.strip():
        return 0.0, "neutral"
    
    # Tokenize and get raw logits
    inputs = tokenizer(
        text, 
        return_tensors="pt", 
        truncation=True,
        max_length=512,  # Explicitly set maximum length
        padding="max_length"  # Optional: pad to same length (optional, not always needed)
        )
    
    # Forward pass
    outputs = model(**inputs)
    logits = outputs.logits[0]
    probs = F.softmax(logits, dim=0)
    
    # Map index to label
    scores = probs.tolist()
    labels = [id2label[i] for i in range(len(scores))]
    label_score_dict = dict(zip(labels, scores))
    
    # Define weighted score: negative=-1, neutral=0, positive=1
    sentiment_value = (
        -1.0 * label_score_dict.get("negative", 0.0) +
         0.0 * label_score_dict.get("neutral", 0.0) +
         1.0 * label_score_dict.get("positive", 0.0)
    )
    
    # Round and classify label
    final_score = round(sentiment_value, 3)
    
    if final_score >= 0.25:
        sentiment_label = "positive"
    elif final_score <= -0.25:
        sentiment_label = "negative"
    else:
        sentiment_label = "neutral"
    
    return final_score, sentiment_label

nltk.download('stopwords')

# Custom stopwords for multiple languages
def get_custom_stopwords():
    custom_stopwords = set(STOPWORDS)
    custom_stopwords.update(nltk_stopwords.words('english'))  # English stopwords
    custom_stopwords.update(nltk_stopwords.words('indonesian'))  # Indonesian stopwords
    return custom_stopwords

def generate_wordcloud(texts):
    """
    Generate a WordCloud based on TF-IDF of the given texts.

    Args:
        texts (list): List of text data (strings) from database.

    Returns:
        str: Base64 encoded image string for WordCloud.
    """
    # If no texts, return None
    if not texts:
        return None
    
    # Get custom stopwords
    custom_stopwords = get_custom_stopwords()

    # Initialize TF-IDF Vectorizer with custom stopwords
    vectorizer = TfidfVectorizer(
        stop_words=list(custom_stopwords),  # Use custom stopwords
        max_features=100,             # Limit the number of features to 100
        ngram_range=(1, 2),           # Use unigrams and bigrams
        lowercase=True,               # Convert text to lowercase
    )

    # Apply TF-IDF to the texts
    X = vectorizer.fit_transform(texts)

    # Get the feature names (words) and their corresponding TF-IDF scores
    feature_names = vectorizer.get_feature_names_out()
    tfidf_scores = X.toarray().sum(axis=0)

    # Create a dictionary: {word: tf-idf score}
    tfidf_dict = dict(zip(feature_names, tfidf_scores))

    # Generate WordCloud based on TF-IDF scores
    wc = WordCloud(
        width=800,
        height=400,
        background_color='white',
        colormap='tab10'
    ).generate_from_frequencies(tfidf_dict)

    # Convert the WordCloud image to base64 encoding
    from io import BytesIO
    import base64
    buffer = BytesIO()
    wc.to_image().save(buffer, format='PNG')
    img_data = base64.b64encode(buffer.getvalue()).decode('utf-8')

    return img_data

def generate_sentiment_heatmap(sentiment_by_day, start_date, end_date):
    # Pastikan start_date dan end_date adalah tipe datetime.date
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    
    # Average sentiment per day, dengan filter nilai None
    averaged_sentiments = {}
    for day, scores in sentiment_by_day.items():
        # Filter out None values
        valid_scores = [score for score in scores if score is not None]
        if valid_scores:  # Check if there are any valid scores after filtering
            averaged_sentiments[day] = sum(valid_scores) / len(valid_scores)
    
    def get_color(score):
        if score is None:
            return 'bg-gray-100'  # Warna default untuk hari tanpa data
        elif score <= -0.5:
            return 'bg-red-400'
        elif score <= 0:
            return 'bg-orange-300'
        elif score <= 0.5:
            return 'bg-green-300'
        else:
            return 'bg-green-600'
    
    # Create full calendar year structure: 53 weeks x 7 days
    start = date(start_date.year, 1, 1)
    heatmap_data = []
    for week in range(53):
        week_data = []
        for day in range(7):
            current_date = start + timedelta(days=week * 7 + day)
            
            # Jika tanggal melebihi end_date atau tidak ada data, beri warna default
            if current_date > end_date or current_date not in averaged_sentiments:
                color = ''  # Kosong untuk hari tanpa data
            else:
                color = get_color(averaged_sentiments.get(current_date))
            
            week_data.append({
                "date": current_date.isoformat(),
                "color": color
            })
        heatmap_data.append(week_data)
    return heatmap_data

# Moving avg sentiment
def calculate_moving_average(sentiment_data, window_size=7):
    # Step 1: Mapping tanggal -> list skor valid
    date_scores = {}
    for row in sentiment_data:
        dt, score = row
        dt = dt if isinstance(dt, date) else datetime.strptime(dt, "%Y-%m-%d").date()
        if score is not None:
            date_scores.setdefault(dt, []).append(score)

    if not date_scores:
        return []

    # Otomatis tentukan start dan end dari data
    all_dates = sorted(date_scores.keys())
    start_date = all_dates[0]
    end_date = all_dates[-1]

    # Step 2: Iterasi tanggal dari start_date hingga end_date
    current_date = start_date
    result = []

    while current_date <= end_date:
        # Ambil window: current_date - (window_size - 1) hari ke belakang
        window_start = current_date - timedelta(days=window_size - 1)
        window_dates = [window_start + timedelta(days=i) for i in range(window_size)]

        # Gabungkan semua skor valid dalam jendela
        window_scores = []
        for d in window_dates:
            scores = date_scores.get(d, [])
            window_scores.extend(scores)

        # Hitung rata-rata jika ada skor valid
        if window_scores:
            avg = sum(window_scores) / len(window_scores)
        else:
            avg = None  # Tidak ada data

        result.append({
            "date": current_date.isoformat(),
            "average": round(avg, 3) if avg is not None else None
        })

        current_date += timedelta(days=1)

    return result

def prepare_actual_sentiment_data(sentiment_data):
    # Step 1: Mapping tanggal -> list skor valid
    date_scores = {}
    for row in sentiment_data:
        dt, score = row
        try:
            # Try to use date object directly first
            dt = dt if isinstance(dt, date) else datetime.strptime(dt, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            # Handle potential formatting issues
            if isinstance(dt, str):
                dt = datetime.strptime(dt, "%Y-%m-%d").date()
            else:
                continue  # Skip invalid dates
                
        if score is not None:
            date_scores.setdefault(dt, []).append(score)
    
    if not date_scores:
        return []
    
    # Get all dates range
    all_dates = sorted(date_scores.keys())
    start_date = all_dates[0]
    end_date = all_dates[-1]
    
    # Step 2: Create results for the full date range, but only include sentiment
    # scores for days that actually have data
    result = []
    current_date = start_date
    while current_date <= end_date:
        scores = date_scores.get(current_date, [])
        
        if scores:  # Only include data points for days with actual sentiment scores
            avg_score = sum(scores) / len(scores)
            result.append({
                "date": current_date.isoformat(),
                "sentiment": round(avg_score, 3)
            })
        
        current_date += timedelta(days=1)
    
    return result

