from flask import Flask, render_template, request, jsonify
import requests
import json
from datetime import datetime  # ✅ Pastikan impor yang benar
import plotly.express as px
import plotly.io as pio
import config  # Import konfigurasi GitHub Gist

app = Flask(__name__)

# URL Gist
GIST_URL = f"https://api.github.com/gists/{config.GITHUB_GIST_ID}"
HEADERS = {"Authorization": f"token {config.GITHUB_TOKEN}"}

# Ambil data dari Gist
def load_data():
    response = requests.get(GIST_URL, headers=HEADERS)
    if response.status_code == 200:
        gist_content = json.loads(response.json()["files"]["ratings.json"]["content"])
        return gist_content
    return []

# Simpan data ke Gist
def save_data(data):
    updated_content = json.dumps(data, indent=4)
    payload = {
        "files": {
            "ratings.json": {"content": updated_content}
        }
    }
    requests.patch(GIST_URL, headers=HEADERS, json=payload)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        date = request.form["date"]
        rating = int(request.form["rating"])
        
        data = load_data()
        data.append({"date": date, "rating": rating})
        save_data(data)

        return jsonify({"success": True, "message": "Rating berhasil disimpan!"})
    
    data = load_data()

    if not data:
        chart_data = {"dates": [], "ratings": []}
    else:
        # Urutkan data berdasarkan tanggal
        sorted_data = sorted(data, key=lambda d: datetime.strptime(d["date"], "%Y-%m-%d"))

        # Ambil 7 data terakhir setelah diurutkan
        last_7_data = sorted_data[-7:]

        # Format ulang tanggal & konversi rating ke integer
        dates = [format_date(d["date"]) for d in last_7_data]
        ratings = [int(float(d["rating"])) for d in last_7_data]  # Konversi float → int

        # Siapkan data untuk template
        chart_data = {"dates": dates, "ratings": ratings}

    return render_template("index.html", chart_data=chart_data)

def format_date(date_str):
    bulan_mapping = {
        1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mei", 6: "Jun",
        7: "Jul", 8: "Agu", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des"
    }
    hari_mapping = {
        0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis",
        4: "Jumat", 5: "Sabtu", 6: "Minggu"
    }

    dt = datetime.strptime(date_str, "%Y-%m-%d")  # ✅ Diperbaiki
    hari = hari_mapping[dt.weekday()]
    bulan = bulan_mapping[dt.month]
    return f"{hari}, {dt.day} {bulan}"

@app.route("/graph")
def graph():
    data = load_data()

    if not data:
        chart_data = {"dates": [], "ratings": []}
    else:
        # Urutkan data berdasarkan tanggal
        sorted_data = sorted(data, key=lambda d: datetime.strptime(d["date"], "%Y-%m-%d"))

        # Ambil 7 data terakhir setelah diurutkan
        last_7_data = sorted_data[-7:]

        # Format ulang tanggal & konversi rating ke integer
        dates = [format_date(d["date"]) for d in last_7_data]
        ratings = [int(float(d["rating"])) for d in last_7_data]  # Konversi float → int

        # Siapkan data untuk template
        chart_data = {"dates": dates, "ratings": ratings}

    return render_template("graph.html", chart_data=chart_data)

if __name__ == "__main__":
    app.run(debug=True)
