from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, make_response
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
import traceback
from flask_mail import Mail, Message
from flask_wtf.csrf import CSRFProtect
from forms import RatingForm, RegisterForm, FeedbackForm
from flask_seasurf import SeaSurf


app = Flask(__name__)
app.config.from_object(Config)
csrf = CSRFProtect(app) 

# 🔹 Konfigurasi Gmail SMTP using GOOGLE APP PASSWORD
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = "luciddream982@gmail.com"
app.config["MAIL_PASSWORD"] = app.config["MAIL_APP_PASSWORD"]
app.config["MAIL_DEFAULT_SENDER"] = "luciddream982@gmail.com"

mail = Mail(app)

# 🔹 Setup Firebase
cred = credentials.Certificate("firebase-credentials.json")
firebase_admin.initialize_app(cred)

@app.route("/firebase-config")
def firebase_config():
    return jsonify({
        "apiKey": app.config["FIREBASE_API_KEY"],
        "authDomain": f"{app.config['FIREBASE_PROJECT_ID']}.firebaseapp.com",
        "projectId": app.config["FIREBASE_PROJECT_ID"],
    })


# 🔹 Konfigurasi Google OAuth
google_bp = make_google_blueprint(
    client_id=app.config["GOOGLE_CLIENT_ID"],
    client_secret=app.config["GOOGLE_CLIENT_SECRET"],
    redirect_to="google_login",
    scope=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"]
)
app.register_blueprint(google_bp, url_prefix="/login")

# LOGIN USER
# 🔹 Setup Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = "login"

# 🔹 Model User untuk Flask-Login
class User(UserMixin):
    def __init__(self, firebase_uid, email, name, given_name, family_name):
        self.id = firebase_uid  # 🔥 Pakai firebase_uid sebagai ID utama
        self.email = email
        self.name = name
        self.given_name = given_name
        self.family_name = family_name

    @property
    def is_authenticated(self):
        return bool(self.id)  # 🔥 Pastikan hanya True jika user valid

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False
    
@login_manager.user_loader
def load_user(firebase_uid):
    try:
        # Verify the Firebase user using Firebase Admin SDK
        try:
            firebase_user = auth.get_user(firebase_uid)
        except (ValueError, firebase_admin.auth.UserNotFoundError):
            return None

        # Extract user details from Firebase
        email = firebase_user.email
        name = firebase_user.display_name or email.split('@')[0]
        
        # Split name into given_name and family_name
        name_parts = name.split()
        given_name = name_parts[0] if name_parts else name
        family_name = name_parts[-1] if len(name_parts) > 1 else ''

        # Create and return User object
        return User(
            firebase_uid, 
            email, 
            name, 
            given_name, 
            family_name
        )
    except Exception as e:
        # Log the error for debugging
        app.logger.error(f"Error loading user {firebase_uid}: {str(e)}")
        return None

# function to refresh user information
def refresh_user_info(user):
    try:
        firebase_user = auth.get_user(user.id)
        
        # Update user information if needed
        updated_name = firebase_user.display_name or user.name
        name_parts = updated_name.split()
        
        return User(
            user.id, 
            firebase_user.email, 
            updated_name, 
            name_parts[0] if name_parts else updated_name,
            name_parts[-1] if len(name_parts) > 1 else ''
        )
    except Exception as e:
        app.logger.error(f"Error refreshing user info: {str(e)}")
        return user


# Register Form
@app.route("/register", methods=["GET", "POST"])
@csrf.exempt
def register():
    form = RegisterForm()
    if request.method == "POST":
        if form.validate_on_submit():
            given_name = form.first_name.data.strip()
            family_name = form.last_name.data.strip() if form.last_name.data else ""
            email = form.email.data
            password = form.password.data
            name = f"{given_name} {family_name}".strip()
            
            try:
                # Create user in Firebase Authentication
                firebase_user = auth.create_user(
                    email=email, 
                    password=password, 
                    display_name=name
                )
                
                # Firebase sign-in to get ID token
                firebase_signin_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={app.config.get('FIREBASE_API_KEY')}"
                
                response = requests.post(firebase_signin_url, json={
                    "email": email,
                    "password": password,
                    "returnSecureToken": True
                })
                
                signin_data = response.json()
                
                if "idToken" not in signin_data:
                    flash("Authentication failed after registration.", "danger")
                    return render_template("auth/sign-up.html", form=form)
                
                # Create User object
                user = User(
                    firebase_user.uid,  # This becomes current_user.id
                    email, 
                    name, 
                    given_name, 
                    family_name
                )
                
                # Login user
                login_user(user)
                
                # Verify that current_user.id is set correctly
                if not current_user.id:
                    flash("User authentication failed.", "danger")
                    return render_template("auth/sign-up.html", form=form)
                
                flash("Awesome! You're in. Welcome!", "success")
                return redirect(url_for("index"))
            
            except firebase_admin.auth.EmailAlreadyExistsError:
                flash("Oops! This email is already registered.", "danger")
            
            except Exception as e:
                app.logger.error(f"Registration error: {traceback.format_exc()}")
                flash(f"Sign-up failed: {str(e)}", "danger")
    
    return render_template("auth/sign-up.html", form=form)

# Sign-in Form using firebase
@app.route("/verify-login", methods=["POST"])
def verify_login():
    if request.content_type != "application/json":
        return jsonify({"success": False, "error": "Invalid Content-Type"}), 415

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "Invalid JSON data"}), 400

    token = data.get("token")
    if not token:
        return jsonify({"success": False, "error": "Token is required"}), 400

    try:
        decoded_token = auth.verify_id_token(token)
        firebase_uid = decoded_token.get("uid")
        email = decoded_token.get("email")
        name = decoded_token.get("name", "")
        given_name = decoded_token.get("given_name", "")
        family_name = decoded_token.get("family_name", "")

        if not firebase_uid or not email:
            return jsonify({"success": False, "error": "Invalid token"}), 401

        # 🔹 Cek apakah user sudah ada di database
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE firebase_uid = %s", (firebase_uid,))
        user_data = cursor.fetchone()

        if not user_data:
            # 🔹 Jika user belum ada, simpan ke database
            cursor.execute(
                "INSERT INTO users (firebase_uid, email, name, given_name, family_name) VALUES (%s, %s, %s, %s, %s)",
                (firebase_uid, email, name, given_name, family_name),
            )
            conn.commit()
            user_data = {
                "firebase_uid": firebase_uid,
                "email": email,
                "name": name,
                "given_name": given_name,
                "family_name": family_name,
            }

        conn.close()

        # 🔹 Buat objek User dan login dengan Flask-Login
        user = User(
            firebase_uid=user_data["firebase_uid"],
            email=user_data["email"],
            name=user_data["name"],
            given_name=user_data.get("given_name", ""),
            family_name=user_data.get("family_name", ""),
        )

        login_user(user)  # 🔥 Login dengan Flask-Login

        session["user_id"] = firebase_uid  # (Opsional)
        session.permanent = True

        return jsonify({"success": True, "user_id": firebase_uid})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 401

@app.route("/login", methods=["POST", "GET"])
@csrf.exempt
def login():
    feedback_form = FeedbackForm()  # Tetap menyertakan feedback_form jika diperlukan

    if request.method == "GET":
        return render_template("home.html", feedback_form=feedback_form)
    
    email = request.form.get("email")
    password = request.form.get("password")

    if not email or not password:
        flash("Oops! Email and password can't be empty", "danger")
        return render_template("home.html", feedback_form=feedback_form)

    # Firebase Authentication
    firebase_api_key = app.config.get("FIREBASE_API_KEY")
    
    # Sign-in URL
    signin_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={firebase_api_key}"

    try:
        # Authenticate user
        response = requests.post(signin_url, json={
            "email": email,
            "password": password,
            "returnSecureToken": True
        })
        signin_data = response.json()

        if "error" in signin_data:
            flash("Hmm... that email or password doesn’t seem right", "danger")
            return render_template("home.html", feedback_form=feedback_form)

        # Extract authentication details
        firebase_uid = signin_data.get("localId")
        id_token = signin_data.get("idToken")

        # Fetch additional user information
        get_user_url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={firebase_api_key}"
        user_info_response = requests.post(get_user_url, json={
            "idToken": id_token
        })
        user_info_data = user_info_response.json()

        # Extract user profile information
        users = user_info_data.get("users", [])
        if not users:
            flash("We couldn’t find your account", "danger")
            return render_template("home.html", feedback_form=feedback_form)

        user_profile = users[0]
        
        # Prepare user data
        name = user_profile.get("displayName") or email.split('@')[0]
        given_name = name.split()[0] if ' ' in name else name
        family_name = name.split()[-1] if ' ' in name else ''

        # Create User object with all required parameters
        user = User(
            firebase_uid, 
            email, 
            name, 
            given_name, 
            family_name
        )

        # Store session information
        session["user_id"] = firebase_uid
        session["id_token"] = id_token

        # Login using Flask-Login
        login_user(user)

        flash("Awesome! You're in. Welcome!", "success")
        return redirect(url_for("index"))

    except Exception as e:
        # Log the full error for debugging
        flash(f"Login failed: Something went wrong on our end.", "danger")
        return render_template("home.html", feedback_form=feedback_form)

@app.route("/google")
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))

    # 🔥 Ambil data user dari Google
    resp = google.get("/oauth2/v2/userinfo")
    if resp.status_code != 200:
        return "Oops! Failed to fetch data from Google", 400

    user_info = resp.json()
    email = user_info.get("email")
    name = user_info.get("name", "No Name")
    given_name = user_info.get("given_name", "")
    family_name = user_info.get("family_name", "")
    picture = user_info.get("picture", "")

    if not email:
        return "This email isn’t available in Google’s data", 400

    try:
        # 🔥 1. Cek apakah user sudah ada di Firebase berdasarkan email
        user_record = auth.get_user_by_email(email)

        # 🔥 2. Cek metode login yang digunakan
        providers = auth.get_user(user_record.uid).provider_data
        provider_ids = [p.provider_id for p in providers]

        if "password" in provider_ids and "google.com" not in provider_ids:
            # Jika akun dibuat dengan Email/Password, tolak login dengan Google
            flash("Email ini sudah terdaftar menggunakan Email/Password. Silakan login secara manual.", "danger")
            return redirect(url_for("login"))

        # ✅ Jika bisa login dengan Google, gunakan UID yang ada
        firebase_uid = user_record.uid

    except firebase_admin.auth.UserNotFoundError:
        # 🔥 3. Jika tidak ada, buat akun baru dengan Google
        firebase_user = auth.create_user(
            email=email,
            display_name=name,
            photo_url=picture
        )
        firebase_uid = firebase_user.uid

    # 🔥 4. Login ke Flask-Login menggunakan UID yang ditemukan atau dibuat
    user = User(firebase_uid, email, name, given_name, family_name)
    login_user(user)

    flash(f"You're in! Welcome back, {name}!", "success")
    return redirect(url_for("index"))

# 🔹 Logout
@app.route("/logout")
def logout():
    print(f"DEBUG: Logging out user: {current_user}")  # 🔍 Debugging

    # 🔹 Hapus user dari Flask-Login
    logout_user()

    # 🔹 Hapus semua data sesi Flask
    session.clear()

    # 🔹 Hapus semua cookie yang terkait dengan sesi
    response = make_response(redirect(url_for("home")))
    response.delete_cookie("session")
    response.delete_cookie("remember_token")  # Jika ada "remember me"
    
    flash("You have been logged out.", "info")
    return response
    #return redirect(url_for("home"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email")
        print(f"Request reset password for: {email}")  # Debugging

        try:
            reset_link = auth.generate_password_reset_link(email)
            print(f"Generated reset link: {reset_link}")  # Debugging

             # 🔥 Kirim email dengan Flask-Mail
            msg = Message(
                "RateMyDays: Reset Password Request",
                recipients=[email],
                body=f"Click the link below to reset your password:\n\n{reset_link}"
            )
            mail.send(msg)

            flash(f"Password reset link sent to {email}", "success")
        except Exception as e:
            print(f"Error generating reset link: {e}")  # Debugging
            flash(f"Error: {str(e)}", "error")

        return redirect(url_for("forgot_password"))
    return render_template("auth/forgot-password.html")


# KONFIGURASI DATABASE
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
    cursor.execute("SELECT date, rating, journal FROM ratings WHERE user_id = %s ORDER BY date ASC", (user_id,))
    data = cursor.fetchall()
    conn.close()
    return data

# Fungsi untuk menyimpan atau memperbarui data
def save_data(user_id, date, rating, journal):
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            # Cek apakah data dengan tanggal yang sama sudah ada
            cursor.execute("SELECT id FROM ratings WHERE date = %s AND user_id = %s", (date, user_id))
            existing = cursor.fetchone()

            if existing:
                cursor.execute("UPDATE ratings SET rating = %s, journal = %s WHERE date = %s AND user_id = %s", (rating, journal, date, user_id))
            else:
                cursor.execute("INSERT INTO ratings (user_id, date, rating, journal) VALUES (%s, %s, %s, %s)", (user_id, date, rating, journal))

            conn.commit()  # Simpan perubahan

@app.route("/update", methods=["POST"])
def update_rating():
    date = request.form["date"]
    rating = int(request.form["rating"])
    journal = request.form.get("journal", "")
    user_id = current_user.id  # 🔹 Gunakan Flask-Login, bukan session

    save_data(user_id, date, rating, journal)  # Langsung panggil fungsi save_data()

    return jsonify({"success": True, "message": f"Rating untuk hari <strong>{format_date(date)}</strong> berhasil diperbarui!"})

# Landing Page
@app.route("/")
def home():
    feedback_form = FeedbackForm()
    return render_template("home.html", user=current_user if current_user.is_authenticated else None, feedback_form=feedback_form)

@app.route("/check_session")
def check_session():
    return jsonify({
        "user_in_session": session.get("user_id"),
        "is_authenticated": current_user.is_authenticated
    })

# USER HOMEPAGE
# Homepage setelah sign-in    
@app.route("/homepage", methods=["GET", "POST"])
@login_required
def index():
    print(f"DEBUG: Current user - {current_user}")  
    print(f"DEBUG: Current user authenticated - {current_user.is_authenticated}")  
    print(f"DEBUG: User ID - {current_user.id}")  
    print(f"DEBUG: User Email - {current_user.email}")  # 🔥 Tambahkan ini

    form = RatingForm()  

    if not current_user.is_authenticated:
        print("DEBUG: User tidak terautentikasi!")
        return redirect(url_for("login"))

    user_id = current_user.id  # 🔹 Gunakan Flask-Login, bukan session manual
    #print("User ID setelah login:", user_id)  # Debugging

    if request.method == "POST":
        if form.validate_on_submit():
            date = form.date.data
            rating = form.rating.data
            journal = form.journal.data.strip()

            print(f"DEBUG: date={date}, rating={rating}, journal='{journal}'")

            # Validasi input
            if not date or not rating:
                return jsonify({"success": False, "message": "Date and rating are required!"}), 400

            try:
                rating = int(rating)  # Konversi rating ke integer
            except ValueError:
                return jsonify({"success": False, "message": "Invalid rating value!"}), 400

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
            cursor.execute("INSERT INTO ratings (user_id, date, rating, journal) VALUES (%s, %s, %s, %s)", (user_id, date, rating, journal))
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
    return render_template("index.html", chart_data=chart_data, given_name=given_name, user=current_user, form=form)


@app.route("/journal", methods=["GET", "POST"])
@login_required
def journal():
    print(f"DEBUG: Current user - {current_user}")  
    print(f"DEBUG: Current user authenticated - {current_user.is_authenticated}")  
    print(f"DEBUG: User ID - {current_user.id}")  
    print(f"DEBUG: User Email - {current_user.email}") 

    if not current_user.is_authenticated:
        print("DEBUG: User tidak terautentikasi!")
        return redirect(url_for("login"))

    user_id = current_user.id 

    data = load_data(user_id)
    
    # Fetch journal entries
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT id, date, rating, journal, 
               DATE_FORMAT(date, '%W') AS day_of_week,
               DATE_FORMAT(date, '%M %d, %Y') AS formatted_date
        FROM ratings 
        WHERE user_id = %s 
        ORDER BY date DESC
    """, (user_id,))
    
    journal_entries = cursor.fetchall()
    conn.close()
    
    given_name = current_user.given_name or current_user.name
    return render_template("journal.html", data=data, journal_entries=journal_entries, given_name=given_name, user=current_user)

@app.route("/delete_entry/<int:entry_id>", methods=["POST"])
@login_required
def delete_entry(entry_id):
    user_id = current_user.id
    
    conn = get_db_connection()
    cursor = conn.cursor()

    # Periksa apakah entri ini milik pengguna yang login
    cursor.execute("SELECT COUNT(*) FROM ratings WHERE id = %s AND user_id = %s", (entry_id, user_id))
    if cursor.fetchone()[0] == 0:
        conn.close()
        return jsonify({"success": False, "message": "Entry not found or unauthorized"}), 403
    
    cursor.execute("DELETE FROM ratings WHERE id = %s", (entry_id,))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "Entry deleted successfully"})

@app.route("/get_entry/<int:entry_id>", methods=["GET"])
@login_required
def get_entry(entry_id):
    user_id = current_user.id
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT id, date, rating, journal, 
               DATE_FORMAT(date, '%W') AS day_of_week,
               DATE_FORMAT(date, '%M %d, %Y') AS formatted_date
        FROM ratings 
        WHERE id = %s AND user_id = %s
    """, (entry_id, user_id))
    
    entry = cursor.fetchone()
    conn.close()
    
    if not entry:
        return jsonify({"success": False, "message": "Entry not found"}), 404
    
    return jsonify({"success": True, "entry": entry})
 
def format_date(date_str):
    bulan_mapping = {
        1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
        7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
    }
    hari_mapping = {
        0: "Mon", 1: "Tue", 2: "Wed", 3: "Thur",
        4: "Fri", 5: "Sat", 6: "Sun"
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

# 🔹 Route untuk menerima feedback dan mengirimkan email
@csrf.exempt
@app.route("/send-feedback", methods=["POST"])
def send_feedback():
    feedback_form = FeedbackForm()

    if feedback_form.validate_on_submit():
        name = feedback_form.name.data
        email = feedback_form.email.data
        message = feedback_form.message.data

        # Kirim email ke admin
        msg = Message(
            subject=f"RateMyDay: Feedback",
            sender=email,
            recipients=["luciddream982@gmail.com.com"],  # Ganti dengan email admin
            body=f"From: {name} ({email})\n\nMessage:\n{message}",
        )

        try:
            mail.send(msg)
            flash("Feedback sent successfully!", "success")
        except Exception as e:
            flash("Failed to send feedback. Try again later.", "danger")
            print(f"Error: {e}")  # Debugging

        return redirect(url_for("home"))

    flash("Please fill out the form correctly.", "warning")
    return redirect(url_for("home"))

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
