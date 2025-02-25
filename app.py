from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
import requests
import json
from datetime import datetime, timedelta, date
from config import Config
import mysql.connector
from flask_dance.contrib.google import make_google_blueprint, google
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import firebase_admin
from firebase_admin import auth, credentials
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
app.config.from_object(Config)

# 🔹 Setup Firebase
cred = credentials.Certificate("firebase-credentials.json")
firebase_admin.initialize_app(cred)

# 🔹 Konfigurasi Google OAuth
google_bp = make_google_blueprint(
    client_id=app.config["GOOGLE_CLIENT_ID"],
    client_secret=app.config["GOOGLE_CLIENT_SECRET"],
    redirect_to="google_login",
    scope=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"]
)
app.register_blueprint(google_bp, url_prefix="/login")

# 🔹 Setup Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, id, email, name, given_name):
        self.id = id
        self.email = email
        self.name = name
        self.given_name = given_name

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    conn.close()
    if user:
        return User(user["id"], user["email"], user.get("name", "User"), user.get("given_name", "User"))
    return None

# Landing Page
@app.route("/")
def home():
    return render_template("home.html", user=current_user if current_user.is_authenticated else None)

# Register Page
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        given_name = request.form.get("first_name", "").strip()
        family_name = request.form.get("last_name", "").strip()
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])

        # Gabungkan given_name dan family_name, hilangkan spasi jika family_name kosong
        name = f"{given_name} {family_name}".strip()

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (name, given_name, family_name, email, password_hash) VALUES (%s, %s, %s, %s, %s)", (name, given_name, family_name, email, password))
            conn.commit()

            # 🔹 Auto-login setelah registrasi
            user_id = cursor.lastrowid
            login_user(User(user_id, email, name, given_name))
            
            flash("Awesome! You're in. Welcome!", "success")
            return redirect(url_for("index"))
        except mysql.connector.IntegrityError:
            flash("Oops! This email is already in use", "danger")
            return redirect(url_for("register"))
        finally:
            cursor.close()
            conn.close()

    return render_template("auth/sign-up.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")  # Gunakan form, bukan JSON
        password = request.form.get("password")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        conn.close()

        if user and user["password_hash"]:  # Pastikan password_hash ada
            if check_password_hash(user["password_hash"], password):
                login_user(User(user["id"], user["email"], user.get("name", "User"), user.get("given_name", "User")))
                flash("You're in! Welcome back!", "success")
                return redirect(url_for("index"))
        flash("Oops! Wrong email or password", "danger")        

    return redirect(url_for("home"))


# 🔹 Login dengan Google
@app.route("/google")
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))

    resp = google.get("/oauth2/v2/userinfo")
    if resp.status_code != 200:
        return "Oops! Failed to fetch data from Google", 400

    user_info = resp.json()
    email = user_info.get("email")
    name = user_info.get("name", "No Name")
    google_id = user_info.get("id")
    given_name = user_info.get("given_name")
    family_name = user_info.get("family_name")
    picture = user_info.get("picture")

    if not email:
        return "This email isn’t available in Google’s data", 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()

    if not user:
        cursor.execute("INSERT INTO users (email, name, google_id, given_name, family_name, picture) VALUES (%s, %s, %s, %s, %s, %s)", 
                       (email, name, google_id, given_name, family_name, picture))
        conn.commit()
        user_id = cursor.lastrowid
    else:
        user_id = user["id"]

    conn.close()

    # 🔹 Gunakan Flask-Login
    user = User(user_id, email, name, given_name)
    login_user(user)  # Simpan ke Flask-Login

    flash(f"You're in! Welcome back!", "success")
    return redirect(url_for("index"))

# 🔹 Logout
@app.route("/logout")
@login_required
def logout():
    logout_user()  # Logout dari Flask-Login
    session.clear()  # Hapus semua session Flask
    #print("User setelah logout:", current_user.is_authenticated)  # Debugging
    return redirect(url_for("home"))


# 🔹 Reset Password
@app.route("/reset-password/<email>")
def reset_password(email):
    try:
        link = auth.generate_password_reset_link(email)
        return jsonify({"success": True, "message": f"Gunakan link berikut untuk reset password: {link}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# Konfigurasi koneksi ke MySQL
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="ratemydays"
    )

# Fungsi untuk mengambil data dari MySQL
def load_data(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT date, rating FROM ratings WHERE user_id = %s ORDER BY date ASC", (user_id,))
    data = cursor.fetchall()
    conn.close()
    return data

# Fungsi untuk menyimpan atau memperbarui data
def save_data(user_id, date, rating):
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            # Cek apakah data dengan tanggal yang sama sudah ada
            cursor.execute("SELECT id FROM ratings WHERE date = %s AND user_id = %s", (date, user_id))
            existing = cursor.fetchone()

            if existing:
                cursor.execute("UPDATE ratings SET rating = %s WHERE date = %s AND user_id = %s", (rating, date, user_id))
            else:
                cursor.execute("INSERT INTO ratings (user_id, date, rating) VALUES (%s, %s, %s)", (user_id, date, rating))

            conn.commit()  # Simpan perubahan

@app.route("/update", methods=["POST"])
def update_rating():
    date = request.form["date"]
    rating = int(request.form["rating"])
    user_id = current_user.id  # 🔹 Gunakan Flask-Login, bukan session

    save_data(user_id, date, rating)  # Langsung panggil fungsi save_data()

    return jsonify({"success": True, "message": f"Rating untuk hari <strong>{format_date(date)}</strong> berhasil diperbarui!"})


@app.route("/homepage", methods=["GET", "POST"])
@login_required
def index():
    user_id = current_user.id  # 🔹 Gunakan Flask-Login, bukan session manual

    #print("User ID setelah login:", user_id)  # Debugging

    if request.method == "POST":
        date = request.form["date"]
        rating = int(request.form["rating"])

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 🔹 Perbaiki pemanggilan load_data() dengan user_id
        data = load_data(user_id)
        
        # Cek apakah data dengan tanggal yang sama sudah ada
        cursor.execute("SELECT rating FROM ratings WHERE date = %s AND user_id = %s", (date, user_id))
        existing = cursor.fetchone()

        if existing:
            conn.close()
            return jsonify({
                "duplicate": True,
                "message": f"Data untuk hari <strong>{format_date(date)}</strong> sudah ada. Apakah ingin memperbarui?",
                "existing_data": existing
            })
        
        # Jika tidak ada data, simpan sebagai entri baru
        cursor.execute("INSERT INTO ratings (user_id, date, rating) VALUES (%s, %s, %s)", (user_id, date, rating))
        conn.commit()
        conn.close()

        return jsonify({"success": True, "message": "Rating berhasil disimpan!"})
    
    data = load_data(user_id)
    range_filter = request.args.get("range", "1w")  # Default ke 1 minggu terakhir
    today = datetime.today()

    if not data:
        chart_data = {"dates": [], "ratings": []}
    else:
        # Urutkan data berdasarkan tanggal
        sorted_data = sorted(data, key=lambda d: d["date"])

        # Filter berdasarkan rentang yang dipilih
        if range_filter == "1w":
            start_date = today - timedelta(days=7)
            filtered_data = [d for d in sorted_data if d["date"] >= start_date.date()]
        elif range_filter == "2w":
            start_date = today - timedelta(days=14)
            filtered_data = [d for d in sorted_data if d["date"] >= start_date.date()]
        elif range_filter == "1m":
            start_date = today - timedelta(days=30)
            filtered_data = [d for d in sorted_data if d["date"] >= start_date.date()]
        elif range_filter == "monthly":
            selected_month = request.args.get("month", today.strftime("%Y-%m"))  # Format: "YYYY-MM"
            filtered_data = [d for d in sorted_data if d["date"].strftime("%Y-%m") == selected_month]
        else:
            filtered_data = sorted_data[-7:]  # Default ke 7 data terakhir

        # Format ulang tanggal & konversi rating ke integer
        dates = [format_date(d["date"]) for d in filtered_data]
        ratings = [int(d["rating"]) for d in filtered_data]

        chart_data = {"dates": dates, "ratings": ratings}
    
    given_name = current_user.given_name or current_user.name
    return render_template("index.html", chart_data=chart_data, given_name=given_name, user=current_user)

def format_date(date_str):
    bulan_mapping = {
        1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mei", 6: "Jun",
        7: "Jul", 8: "Agu", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des"
    }
    hari_mapping = {
        0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis",
        4: "Jumat", 5: "Sabtu", 6: "Minggu"
    }

    # 🔹 Jika `date_str` adalah objek `datetime.date`, konversi ke string
    if isinstance(date_str, date):  
        date_str = date_str.strftime("%Y-%m-%d")  # Konversi ke string
    
    # 🔹 Sekarang, pastikan `date_str` sudah string sebelum `strptime`
    if isinstance(date_str, str):
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    else:
        raise ValueError("Format tanggal tidak valid")
    
    hari = hari_mapping[dt.weekday()]
    bulan = bulan_mapping[dt.month]
    return f"{hari}, {dt.day} {bulan}"

@app.route("/graph")
def graph():
    data = load_data()
    range_filter = request.args.get("range", "1w")  # Default ke 1 minggu terakhir
    today = datetime.today()

    if not data:
        chart_data = {"dates": [], "ratings": []}
    else:
        # Urutkan data berdasarkan tanggal
        sorted_data = sorted(data, key=lambda d: datetime.strptime(d["date"], "%Y-%m-%d"))

        # Filter berdasarkan rentang yang dipilih
        if range_filter == "1w":
            start_date = today - timedelta(days=7)
            filtered_data = [d for d in sorted_data if datetime.strptime(d["date"], "%Y-%m-%d") >= start_date]
        elif range_filter == "2w":
            start_date = today - timedelta(days=14)
            filtered_data = [d for d in sorted_data if datetime.strptime(d["date"], "%Y-%m-%d") >= start_date]
        elif range_filter == "1m":
            start_date = today - timedelta(days=30)
            filtered_data = [d for d in sorted_data if datetime.strptime(d["date"], "%Y-%m-%d") >= start_date]
        elif range_filter == "monthly":
            selected_month = request.args.get("month", today.strftime("%Y-%m"))  # Format: "YYYY-MM"
            filtered_data = [d for d in sorted_data if d["date"].startswith(selected_month)]
        else:
            filtered_data = sorted_data[-7:]  # Default ke 7 data terakhir

        # Format ulang tanggal & konversi rating ke integer
        dates = [format_date(d["date"]) for d in filtered_data]
        ratings = [int(float(d["rating"])) for d in filtered_data]

        chart_data = {"dates": dates, "ratings": ratings}

    return render_template("graph.html", chart_data=chart_data)

if __name__ == "__main__":
    app.run(debug=True)
