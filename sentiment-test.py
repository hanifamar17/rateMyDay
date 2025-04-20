from app import get_db_connection
from analysis import analyze_sentiment
import time

def update_existing_sentiments():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Ambil semua entri ratings yang memiliki journal
    cursor.execute("""
        SELECT id, journal FROM ratings
        WHERE journal IS NOT NULL AND journal != ''
    """)
    rows = cursor.fetchall()

    print(f"🔍 Menemukan {len(rows)} jurnal untuk diperbarui.")

    for row in rows:
        journal = row["journal"]
        rating_id = row["id"]

        # Pastikan journal tidak kosong (double check)
        if not journal.strip():
            continue

        sentiment_score, sentiment_label = analyze_sentiment(journal)

        # Update nilai sentiment
        cursor.execute("""
            UPDATE ratings 
            SET sentiment_score = %s, sentiment_label = %s 
            WHERE id = %s
        """, (sentiment_score, sentiment_label, rating_id))

        print(f"✅ ID {rating_id} updated with sentiment_score: {sentiment_score}, sentiment_label: {sentiment_label}")
        time.sleep(0.05)  # Opsional: beri jeda agar tidak overload

    conn.commit()
    conn.close()
    print("🎉 Semua data selesai diperbarui.")

# Jalankan fungsi
if __name__ == "__main__":
    update_existing_sentiments()